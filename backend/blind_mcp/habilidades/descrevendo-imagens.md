---
nome: descrevendo-imagens
quando: Ao descrever foto, imagem, vídeo, captura de tela, gráfico ou qualquer coisa visual para uma pessoa cega.
palavras: blindimage, imagem, foto, fotografia, figura, vídeo, video, gráfico, grafico, print, captura, descrever, descrição, descricao, audiodescrição, tela
---
# Descrevendo imagens

Base: guias do Perkins School for the Blind, RNIB e W3C sobre texto alternativo e audiodescrição.

**Ideia central:** descreva o que a pessoa precisa para entender a imagem, como se estivesse ao telefone com um amigo que não pode ver. Responda: o que é, por que importa, o que preciso saber.

**Se a pessoa perguntou algo específico** ("onde estão as chaves?", "essa carne está pronta?", "o que diz a placa?"), responda só isso, com o que ela precisa fazer em seguida. Estudos com cegos mostram que a "descrição da cena inteira" no começo atrapalha: eles não querem saber que há uma mesa. Descrição completa só quando pedida ou quando não há pergunta.

**Nome:** a ferramenta de imagem se chama "blindimage" (describe_image e ver_imagem). Quando a pessoa disser "pergunta pro blindimage" ou "vê no blindimage", use elas e diga "blindimage" ao falar dela.

**Quem descreve:** se `describe_image` disser que nenhum modelo de visão respondeu, chame `ver_imagem` com o arquivo: ela entrega a imagem a você (o modelo da conversa), e você descreve seguindo estas regras.

## Ordem
1. **Tipo e assunto em uma frase**: "Foto de uma sala com duas pessoas à mesa", "Gráfico de barras de gastos por mês", "Captura de tela de uma conversa".
2. **O que importa para o contexto.** Se veio numa conversa, o que o amigo quis mostrar? Se é um documento, o dado principal.
3. **Detalhes** só depois, e só os que mudam o entendimento: ações, lugar, objetos principais, cores relevantes, expressão visível.
4. **Ofereça mais**: "Quer mais detalhe?". Não despeje tudo de uma vez.

## Regras
- **Texto na imagem: leia palavra por palavra**, sem resumir (placas, prints, cartazes, recibos). Diga quando não deu para ler.
- **Gente:** descreva sim, a pessoa cega quer saber como as pessoas aparecem (família, amigos, ela mesma). Diga quantas são, o que fazem, roupa, cabelo, idade aproximada e expressão, com "parece" quando houver dúvida. **Nunca identifique alguém pelo rosto** nem invente nome: use o nome só se estiver escrito na imagem, no contato de quem enviou ou se a pessoa disser. Quando o nome é conhecido, use-o em vez de descrever o rosto toda vez.
- **Se o modelo se recusar** ("não posso identificar pessoas"), isso não é descrição: o Blind já tenta outro modelo. Se todos se recusarem, diga com clareza e sugira pedir a alguém de confiança, em vez de inventar.
- **Animais e objetos comuns:** diga o nome ("um cachorro poodle"), sem descrever o que todo mundo já imagina.
- **Gráfico ou tabela:** tipo, o que mostram os eixos, a tendência e os números principais. Ofereça os valores todos.
- **Vídeo:** descreva o que acontece em ordem, curto, e o áudio se houver fala (transcreva).
- **Não invente.** A descrição automática erra (já confundiu elefantes com gorilas, bocejo com grito). Se a imagem está borrada, escura ou cortada, diga. Use "parece" quando houver dúvida.
- **Não repita** o que a legenda ou a mensagem já disse.
- **Sem "imagem de" no começo** quando o tipo já está claro. Sem opinião ("linda", "feia") a menos que a pessoa pergunte.
- **Qualidade da imagem:** o conjunto VizWiz, feito com fotos reais de pessoas cegas, lista os defeitos mais comuns: borrada, clara demais, escura demais, enquadramento errado (o objeto cortado ou fora), algo na frente da câmera e imagem de cabeça para baixo ou de lado. Se for o caso, diga qual ("a foto saiu escura e o rótulo está cortado") e sugira tirar outra, sem culpar a pessoa. Se não dá para reconhecer o que é, diga isso em vez de inventar.
- **Remédio, dose, dinheiro, documento, validade:** leia sempre o que está escrito. A pessoa muitas vezes está sozinha. Diga o grau de certeza, repita o número lido separado e, se estiver borrado, peça outra foto. Fale em voz (veja dados-sensiveis), sem escrever o valor.
- **Conteúdo sensível** (rosto íntimo, documento com dados): descreva o necessário e avise antes de ler números de documento em voz alta se houver outras pessoas por perto.
- **Pergunta de acompanhamento e foto melhor:** a pessoa pode perguntar mais ("a placa diz o quê?", "a foto está focada?") e mandar outra foto de outro ângulo. Responda só ao que perguntou.
- **Privacidade:** a imagem vai para um modelo de IA na internet. Para dado sensível, leia mesmo assim e siga a habilidade dados-sensiveis: voz sem expor, nada escrito.
- **Se a pessoa duvidar** ("tem certeza que é vermelha?"), olhe de novo e corrija sem rodeio se errou.

## Exemplo
Ruim: "Uma foto de um cachorro."
Bom: "Foto de um poodle preto correndo na grama atrás de uma bola vermelha. Parece estar sorrindo. Quer mais detalhe do cenário?"
