"""Regras de seguranca do Blind (seguranca.py): protegido, Registro, desligar, som, tela e onde o blind-docs grava."""

from pathlib import Path

import pytest

from blind_mcp import seguranca as sg


def bloqueia(server, tool, **args):
    with pytest.raises(sg.BloqueioDeSeguranca):
        sg.verificar_chamada(server, tool, args)


def libera(server, tool, **args):
    sg.verificar_chamada(server, tool, args)


# ---------------------------------------------------------------- Windows e Arquivos de Programas
@pytest.mark.parametrize("cmd", [
    r"Remove-Item C:\Windows\System32\drivers\etc\hosts",
    r"rm -Recurse -Force 'C:\Program Files\Algum'",
    r"del C:/Windows/notepad.exe",
    r"Remove-Item $env:windir\Temp\x.txt",
    r"Remove-Item ${env:ProgramFiles}\App -Recurse",
    r'cmd /c "rd /s /q %SystemRoot%\Temp"',
    r"Move-Item 'C:\Program Files (x86)\X\a.dll' C:\Users\olive\Documents",
    r"Set-Content C:\Windows\win.ini 'x'",
])
def test_comando_nao_apaga_windows_nem_programas(cmd):
    bloqueia("windows", "PowerShell", command=cmd)
    bloqueia("blind-commander", "start_process", command=cmd)


def test_ler_windows_pode_e_apagar_na_pasta_do_usuario_pode():
    libera("windows", "PowerShell", command=r"Get-ChildItem C:\Windows | Select-Object -First 5")
    libera("windows", "PowerShell", command=r"Get-Content 'C:\Program Files\App\leia.txt'")
    libera("windows", "PowerShell", command=r"Remove-Item C:\Users\olive\Downloads\velho.txt")


def test_ferramentas_de_arquivo_respeitam_pastas_protegidas():
    bloqueia("windows", "FileSystem", mode="delete", path=r"C:\Windows\Temp\a.txt")
    bloqueia("windows", "FileSystem", mode="write", path=r"C:\Program Files\X\a.txt", content="x")
    bloqueia("windows", "FileSystem", mode="copy", path=r"C:\Users\olive\Documents\a.txt", destination=r"C:\Windows\a.txt")
    bloqueia("windows", "FileSystem", mode="move", path=r"C:\Windows\a.txt", destination=r"C:\Users\olive\Documents\a.txt")
    libera("windows", "FileSystem", mode="copy", path=r"C:\Windows\win.ini", destination=r"C:\Users\olive\Documents\win.ini")
    libera("windows", "FileSystem", mode="read", path=r"C:\Windows\win.ini")
    bloqueia("blind-commander", "write_file", path=r"C:\Windows\x.txt", content="a")
    bloqueia("blind-commander", "move_file", source=r"C:\Users\olive\a.txt", destination=r"C:\Program Files\a.txt")
    bloqueia("blind-commander", "edit_block", file_path=r"C:\Windows\win.ini", old_string="a", new_string="b")
    libera("blind-commander", "write_file", path=r"C:\Users\olive\Documents\a.txt", content="a")


def test_caminho_com_ponto_ponto_nao_escapa():
    assert sg.caminho_protegido(r"C:\Users\olive\..\..\Windows\x")
    assert not sg.caminho_protegido(r"C:\Users\olive\Documents\Windows Notes.txt")


# ---------------------------------------------------------------- Registro
@pytest.mark.parametrize("cmd", [
    r"reg add HKCU\Software\X /v a /d 1",
    r"reg delete HKLM\Software\X /f",
    r"Set-ItemProperty -Path HKCU:\Software\X -Name a -Value 1",
    r"New-Item -Path 'HKLM:\SOFTWARE\Novo'",
    r"Remove-ItemProperty -Path Registry::HKEY_CURRENT_USER\Software\X -Name a",
    r"regedit /s arquivo.reg",
    r"[Microsoft.Win32.Registry]::CurrentUser.OpenSubKey('x',$true).SetValue('a',1)",
])
def test_registro_nao_se_altera(cmd):
    bloqueia("windows", "PowerShell", command=cmd)


def test_registro_ferramenta_ler_pode_gravar_nao():
    libera("windows", "Registry", mode="get", path=r"HKLM:\SOFTWARE\Microsoft", name="x")
    libera("windows", "Registry", mode="list", path=r"HKCU:\Software")
    bloqueia("windows", "Registry", mode="set", path=r"HKCU:\Software\X", name="a", value="1", type="String")
    bloqueia("windows", "Registry", mode="delete", path=r"HKCU:\Software\X")
    libera("windows", "PowerShell", command=r"Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion'")
    libera("windows", "PowerShell", command=r"reg query HKCU\Software")


# ---------------------------------------------------------------- desligar
@pytest.mark.parametrize("cmd", ["shutdown /s /t 0", "shutdown.exe /r", "Stop-Computer -Force", "Restart-Computer",
                                 "wmic os where primary=1 reboot", "(gwmi win32_operatingsystem).Win32Shutdown(1)"])
def test_nao_desliga_nem_reinicia(cmd):
    bloqueia("windows", "PowerShell", command=cmd)
    bloqueia("blind-commander", "start_process", command=cmd)
    bloqueia("blind-commander", "interact_with_process", pid=1, input=cmd)


def test_nao_abrir_regedit_pelo_launcher():
    bloqueia("windows", "App", mode="launch", name="regedit")
    bloqueia("agent-desktop", "launch_app", target="regedit.exe")


# ---------------------------------------------------------------- som e tela
def test_som_nunca_mudo_nem_abaixo_do_minimo():
    bloqueia("windows", "PowerShell", command="nircmd.exe mutesysvolume 1")
    bloqueia("windows", "PowerShell", command="$o.SetMute($true, [guid]::Empty)")
    bloqueia("windows", "PowerShell", command="(New-Object -ComObject WScript.Shell).SendKeys([char]173)")
    bloqueia("windows", "PowerShell", command="$v.SetMasterVolumeLevelScalar(0.05, [guid]::Empty)")
    bloqueia("windows", "PowerShell", command="$v.SetMasterVolumeLevelScalar(0, [guid]::Empty)")
    bloqueia("windows", "PowerShell", command="nircmd.exe setsysvolume 2000")
    bloqueia("windows", "PowerShell", command="$v.SetMasterVolumeLevelScalar($x, [guid]::Empty)")  # nao da para conferir
    libera("windows", "PowerShell", command="$v.SetMasterVolumeLevelScalar(0.4, [guid]::Empty)")
    libera("windows", "PowerShell", command="nircmd.exe setsysvolume 30000")
    bloqueia("agent-desktop", "press_keys", keys="VolumeMute")
    libera("agent-desktop", "press_keys", keys="VolumeDown")
    libera("agent-desktop", "press_keys", keys="VolumeUp")
    bloqueia("agent-desktop", "press_keys", keys="VolumeDown", repeat=20)


def test_tela_nunca_apaga_nem_brilho_minimo():
    bloqueia("windows", "PowerShell", command="nircmd.exe monitor off")
    bloqueia("windows", "PowerShell", command="(Add-Type ...)::SendMessage(0xFFFF, 0x0112, 0xF170, 2)")
    bloqueia("windows", "PowerShell", command="powercfg /change monitor-timeout-ac 1")
    bloqueia("windows", "PowerShell",
             command="(Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightnessMethods).WmiSetBrightness(1,0)")
    bloqueia("windows", "PowerShell",
             command="(Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightnessMethods).WmiSetBrightness(1,10)")
    libera("windows", "PowerShell",
           command="(Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightnessMethods).WmiSetBrightness(1,60)")


# ---------------------------------------------------------------- onde o blind-docs grava
def test_blind_docs_so_grava_em_downloads_documentos_musicas_videos(monkeypatch):
    monkeypatch.delenv("BLIND_PASTAS_EXTRAS", raising=False)
    home = Path.home()
    for nome in ("Downloads", "Documents", "Music", "Videos"):
        sg.conferir_gravacao_blind_docs(home / nome / "a.docx")
        sg.conferir_gravacao_blind_docs(home / nome / "nova pasta" / "sub" / "a.docx")  # subpasta nova pode
    for ruim in (home / "Desktop" / "a.docx", home / "a.docx", Path(r"C:\Windows\a.docx"), Path(r"C:\Program Files\a.docx"),
                 Path(r"C:\temp\a.docx"), home / "Documents" / ".." / "Desktop" / "a.docx"):
        with pytest.raises(sg.BloqueioDeSeguranca):
            sg.conferir_gravacao_blind_docs(ruim)


def test_writer_save_recusa_pasta_fora_da_lista(monkeypatch, tmp_path):
    from core.writer.smart_writer import SmartWriter

    w = SmartWriter(tmp_path)
    d = w.draft_document("T", "texto", "a.txt")
    monkeypatch.delenv("BLIND_PASTAS_EXTRAS", raising=False)
    d["target_path"] = str(Path.home() / "Desktop" / "a.txt")
    with pytest.raises(sg.BloqueioDeSeguranca):
        w.save_document(d)
