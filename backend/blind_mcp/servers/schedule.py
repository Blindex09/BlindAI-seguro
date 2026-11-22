"""Servidor MCP: blind-schedule, agendamento do Blind (tarefas e lembretes falados).

Ferramentas: blindschedule_create, blindschedule_list, blindschedule_snooze, blindschedule_delete.
Antes ficavam no blind-memory como schedule_*; a tabela `schedules` continua no mesmo banco (blind_memory.db),
entao os lembretes ja criados seguem valendo. Eventos de calendario ficam no conector Google Calendar do Claude.
Dispara lembretes falados no horario via SAPI do Windows; so a copia dona (core.leader "lembretes") fala.
"""

from __future__ import annotations

import datetime as dt
import os
import sqlite3
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List

from mcp.server.fastmcp import FastMCP

from ._common import BACKEND_DIR, run_blocking

mcp = FastMCP("blind-schedule")

DATA_DIR = Path(os.environ.get("BLIND_DATA_DIR") or (BACKEND_DIR / "data"))
MEMORY_DB = DATA_DIR / "blind_memory.db"


def _init_db() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(MEMORY_DB) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schedules (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                message TEXT NOT NULL,
                next_run_at REAL NOT NULL,
                repeat_daily INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'active',
                created_at REAL NOT NULL
            )
            """
        )
        cols = {r[1] for r in conn.execute("PRAGMA table_info(schedules)").fetchall()}
        if "repeat_days" not in cols:
            conn.execute("ALTER TABLE schedules ADD COLUMN repeat_days INTEGER NOT NULL DEFAULT 0")
            conn.execute("UPDATE schedules SET repeat_days = 1 WHERE repeat_daily = 1")
        conn.commit()


_init_db()


def _speak_reminder_sapi(text: str) -> None:
    """Anuncia um lembrete falado via SAPI sem roubar o foco do teclado."""
    clean = (text or "").replace("'", " ").replace('"', " ").strip()
    if not clean:
        return
    ps_cmd = (
        "Add-Type -AssemblyName System.Speech; "
        "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        f"$s.Speak('Lembrete do Blind AI: {clean}')"
    )
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_cmd],
            capture_output=True,
            timeout=25,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception:
        pass


def _next_after(next_run: float, days: int, now: float) -> float:
    """Proxima execucao de um lembrete repetido, sempre no futuro (evita disparar varias vezes seguidas por atraso)."""
    step = max(1, days) * 86400.0
    nxt = next_run + step
    if nxt <= now:
        nxt += ((now - nxt) // step + 1) * step
    return nxt


def _scheduler_worker() -> None:
    """Verifica lembretes vencidos a cada 15 segundos e anuncia por voz. Atrasados avisam que estao atrasados."""
    from core.leader import leader_for

    leader = leader_for("lembretes")
    while True:
        try:
            if not leader.try_acquire():
                # Outra copia (Claude ou Electron) e a dona dos lembretes: so ela fala, para nao tocar em dobro.
                time.sleep(15)
                continue
            now = time.time()
            due: List[tuple] = []
            with sqlite3.connect(MEMORY_DB) as conn:
                cur = conn.cursor()
                cur.execute(
                    """
                    SELECT id, title, message, repeat_days, next_run_at
                    FROM schedules
                    WHERE status = 'active' AND next_run_at <= ?
                    """,
                    (now,),
                )
                due = cur.fetchall()
                for sched_id, _title, _msg, repeat_days, next_run in due:
                    if repeat_days:
                        conn.execute(
                            "UPDATE schedules SET next_run_at = ? WHERE id = ?",
                            (_next_after(next_run, int(repeat_days), now), sched_id),
                        )
                    else:
                        conn.execute(
                            "UPDATE schedules SET status = 'completed' WHERE id = ?",
                            (sched_id,),
                        )
                if due:
                    conn.commit()
            for _sched_id, title, msg, _rep, next_run in due:
                atraso_min = int((now - next_run) // 60)
                prefix = f"Atrasado em {atraso_min} minutos. " if atraso_min >= 2 else ""
                _speak_reminder_sapi(f"{prefix}{title}. {msg}")
        except Exception:
            pass
        time.sleep(15)


threading.Thread(target=_scheduler_worker, name="blind-schedule-scheduler", daemon=True).start()


def _create_sync(
    title: str,
    message: str,
    delay_minutes: int = 0,
    run_at_hhmm: str = "",
    repeat_daily: bool = False,
    repeat: str = "",
) -> Dict[str, Any]:
    now = time.time()
    rep = (repeat or "").strip().lower()
    if rep in {"diario", "diaria", "daily", "todo dia"}:
        dias = 1
    elif rep in {"semanal", "semana", "weekly", "toda semana"}:
        dias = 7
    elif rep in {"", "nenhum", "nao", "none"}:
        dias = 1 if repeat_daily else 0
    else:
        raise ValueError("repeat aceita: nenhum, diario ou semanal.")
    if run_at_hhmm and ":" in run_at_hhmm:
        hh_s, mm_s = run_at_hhmm.strip().split(":", 1)
        now_dt = dt.datetime.now()
        target_dt = now_dt.replace(hour=int(hh_s), minute=int(mm_s), second=0, microsecond=0)
        if target_dt.timestamp() <= now:
            target_dt += dt.timedelta(days=1)
        next_run = target_dt.timestamp()
    else:
        mins = max(1, int(delay_minutes or 1))
        next_run = now + mins * 60.0

    sched_id = f"sched_{uuid.uuid4().hex[:8]}"
    with sqlite3.connect(MEMORY_DB) as conn:
        conn.execute(
            """
            INSERT INTO schedules (id, title, message, next_run_at, repeat_daily, repeat_days, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, 'active', ?)
            """,
            (sched_id, title.strip(), message.strip(), next_run, 1 if dias == 1 else 0, dias, now),
        )
        conn.commit()

    when_str = dt.datetime.fromtimestamp(next_run).strftime("%d/%m/%Y %H:%M")
    return {
        "ok": True,
        "id": sched_id,
        "title": title.strip(),
        "message": message.strip(),
        "scheduled_for": when_str,
        "repeat_daily": dias == 1,
        "repete": {0: "nao repete", 1: "todo dia", 7: "toda semana"}.get(dias, f"a cada {dias} dias"),
        "aviso": "O lembrete so fala enquanto o servidor blind-schedule estiver rodando (Claude ou app aberto). "
                 "Se estiver fechado na hora, ele avisa como 'atrasado' quando abrir.",
    }


@mcp.tool()
async def blindschedule_create(
    title: str,
    message: str,
    delay_minutes: int = 0,
    run_at_hhmm: str = "",
    repeat_daily: bool = False,
    repeat: str = "",
) -> Dict[str, Any]:
    """Cria um lembrete falado agendado (por delay_minutes, ex: 15, ou horario fixo run_at_hhmm, ex: '09:00').
    `repeat`: 'nenhum' (padrao), 'diario' ou 'semanal'. Quando chegar o horario, o Blind AI anuncia o lembrete em voz alta
    via SAPI. So fala com o servidor blind-schedule aberto; se estava fechado, avisa 'atrasado' depois."""
    return await run_blocking(_create_sync, title, message, delay_minutes, run_at_hhmm, repeat_daily, repeat)


def _list_sync(incluir_concluidos: bool = False) -> Dict[str, Any]:
    where = "" if incluir_concluidos else "WHERE status = 'active'"
    with sqlite3.connect(MEMORY_DB) as conn:
        cur = conn.cursor()
        cur.execute(
            f"""
            SELECT id, title, message, next_run_at, repeat_days, status
            FROM schedules
            {where}
            ORDER BY (status = 'active') DESC, next_run_at ASC
            """
        )
        items = [
            {
                "id": row[0],
                "title": row[1],
                "message": row[2],
                "scheduled_for": dt.datetime.fromtimestamp(row[3]).strftime("%d/%m/%Y %H:%M"),
                "repeat_daily": row[4] == 1,
                "repete": {0: "nao repete", 1: "todo dia", 7: "toda semana"}.get(row[4], f"a cada {row[4]} dias"),
                "status": row[5],
            }
            for row in cur.fetchall()
        ]
    return {"ok": True, "count": len(items), "schedules": items}


@mcp.tool()
async def blindschedule_list(incluir_concluidos: bool = False) -> Dict[str, Any]:
    """Lista os lembretes/tarefas falados que a pessoa agendou (a agenda do Blind), do mais proximo ao mais distante.
    Com incluir_concluidos=true mostra tambem os que ja tocaram. Eventos de calendario ficam no conector de Calendar do Claude."""
    return await run_blocking(_list_sync, incluir_concluidos)


def _delete_sync(schedule_id: str) -> Dict[str, Any]:
    ref = (schedule_id or "").strip()
    if not ref:
        raise ValueError("Informe o codigo ou o titulo do lembrete.")
    with sqlite3.connect(MEMORY_DB) as conn:
        cur = conn.execute("DELETE FROM schedules WHERE id = ?", (ref,))
        if cur.rowcount > 0:
            conn.commit()
            return {"ok": True, "id": ref, "deleted": True}
        like = f"%{ref.lower()}%"
        rows = conn.execute(
            "SELECT id, title, message FROM schedules WHERE lower(title) LIKE ? OR lower(message) LIKE ?", (like, like)
        ).fetchall()
        if len(rows) == 1:
            conn.execute("DELETE FROM schedules WHERE id = ?", (rows[0][0],))
            conn.commit()
            return {"ok": True, "id": rows[0][0], "title": rows[0][1], "deleted": True}
        if len(rows) > 1:
            return {
                "ok": False,
                "deleted": False,
                "error": "Mais de um lembrete combina. Pergunte qual e chame de novo com o codigo.",
                "candidatos": [{"id": r[0], "title": r[1], "message": r[2]} for r in rows],
            }
    return {"ok": True, "id": ref, "deleted": False, "error": "Nenhum lembrete com esse codigo ou titulo."}


@mcp.tool()
async def blindschedule_delete(schedule_id: str) -> Dict[str, Any]:
    """Cancela e remove um lembrete. `schedule_id` aceita o codigo (sched_...) OU parte do titulo/texto
    (ex: 'remedio'). Se mais de um combinar, nada e apagado e a lista de candidatos volta para voce perguntar."""
    return await run_blocking(_delete_sync, schedule_id)


def _snooze_sync(schedule_id: str, minutes: int = 10) -> Dict[str, Any]:
    ref = (schedule_id or "").strip()
    if not ref:
        raise ValueError("Informe o codigo ou o titulo do lembrete.")
    mins = max(1, min(int(minutes or 10), 24 * 60))
    now = time.time()
    like = f"%{ref.lower()}%"
    with sqlite3.connect(MEMORY_DB) as conn:
        rows = conn.execute("SELECT id, title, status, repeat_days FROM schedules WHERE id = ?", (ref,)).fetchall()
        if not rows:
            rows = conn.execute(
                "SELECT id, title, status, repeat_days FROM schedules WHERE lower(title) LIKE ? OR lower(message) LIKE ? "
                "ORDER BY next_run_at DESC", (like, like)).fetchall()
        if not rows:
            return {"ok": False, "error": "Nenhum lembrete com esse codigo ou titulo."}
        if len(rows) > 1:
            return {"ok": False, "error": "Mais de um combina. Pergunte qual e chame de novo com o codigo.",
                    "candidatos": [{"id": r[0], "title": r[1]} for r in rows]}
        sid, title, status, repeat_days = rows[0]
        if repeat_days:
            # repetido: cria um aviso unico novo e mantem a repeticao
            new_id = f"sched_{uuid.uuid4().hex[:8]}"
            msg = conn.execute("SELECT message FROM schedules WHERE id = ?", (sid,)).fetchone()[0]
            conn.execute(
                "INSERT INTO schedules (id, title, message, next_run_at, repeat_daily, repeat_days, status, created_at) "
                "VALUES (?, ?, ?, ?, 0, 0, 'active', ?)", (new_id, title, msg, now + mins * 60.0, now))
            sid = new_id
        else:
            conn.execute("UPDATE schedules SET next_run_at = ?, status = 'active' WHERE id = ?", (now + mins * 60.0, sid))
        conn.commit()
    return {"ok": True, "id": sid, "title": title, "adiado_por_minutos": mins,
            "novo_horario": dt.datetime.fromtimestamp(now + mins * 60.0).strftime("%d/%m/%Y %H:%M")}


@mcp.tool()
async def blindschedule_snooze(schedule_id: str, minutes: int = 10) -> Dict[str, Any]:
    """Adia um lembrete por `minutes` minutos (padrao 10). Aceita o codigo (sched_...) ou parte do titulo. Em lembrete
    repetido, cria um aviso unico novo e mantem a repeticao. Serve tambem para reativar um que acabou de tocar."""
    return await run_blocking(_snooze_sync, schedule_id, minutes)


if __name__ == "__main__":
    from . import _audit

    _audit.install_audit(mcp, "blind-schedule")
    mcp.run()
