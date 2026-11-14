# Teste isolado do MAX30102

Teste da aquisição óptica bruta na ESP32 clássica. Não calcula BPM nem SpO₂:
primeiro verifica comunicação, configuração e resposta dos canais vermelho e IR.
Não inicializa Wi-Fi, MQTT, MPU6050, NTC, botão ou motor. Acessa somente 0x57.
Se os demais componentes continuarem conectados, o isolamento é apenas de software.

## Conexões e alimentação

- SDA: GPIO21; SCL: GPIO22; GND comum.
- Barramento I²C: 100 kHz; serial: 115200 baud.
- Alimentar a entrada correta do módulo conforme seus reguladores; não presumir
  que todo pino aceita 5 V. Os sinais no lado da ESP32 devem respeitar 3,3 V.
- Fazer alterações de ligação com a alimentação desligada.
- A montagem original interfere na inicialização e no acesso à flash. Se isso
  ocorrer, registrar a falha e corrigir/isolar a ligação responsável antes de
  atribuir a ausência de amostras ao MAX30102.

## Reaproveitamento e diferenças

`src/MAX30105.cpp` e `.h` foram copiados do projeto original; apenas espaços
no fim de linhas do `.cpp` foram removidos para publicação.
`source_provenance.json` registra origem e SHA-256. São usados para inicializar
e configurar o sensor com os mesmos parâmetros do projeto: vermelho + IR,
400 amostras/s, média de quatro, pulso de 411 µs e faixa ADC de 4096 nA.
As amplitudes são 0x0A para vermelho e 0x1F para IR.

O teste confere os registradores após a configuração. A aquisição lê diretamente
o FIFO em blocos de até cinco amostras, validando a contagem de bytes recebida,
para não usar o buffer circular de quatro posições que falhou no teste do driver.
Falhas não são convertidas em uma amostra IR de valor zero. Na versão v3,
os ponteiros são lidos individualmente, como no driver original. Overflow é
registrado e seu contador é limpo; amostras disponíveis são lidas com `gap=true`.
Se os ponteiros coincidem durante overflow, o estado é ambíguo e os ponteiros
são limpos. Reset do sensor provoca reinicialização explícita.
O diagnóstico inclui uma leitura agrupada dos ponteiros para comparação;
ela ocorre depois das leituras individuais, portanto pequenas diferenças
podem resultar de novas amostras produzidas entre transações.

A validação de 0x08 considera apenas média e rollover (bits 7:4); o limiar de
interrupção de FIFO quase cheio não participa desta aquisição por consulta.

## Saídas

Cada linha serial é JSON. `boot` identifica firmware, pinos e motivo de reset;
`identity` informa identificadores; `config` confirma configuração lida;
`sample` traz sequência, instante de leitura do FIFO em ms, vermelho e IR brutos.
`status` resume uma janela aproximadamente de um segundo, com mínimos, máximos,
médias, contagem de amostras e erros. Sem amostras, as estatísticas são omitidas.
Erros I²C, overflow, ausência prolongada de amostras e reset do sensor têm eventos
próprios. Valores ópticos são contagens sem unidade física calibrada.
`gap=true` informa um contador de overflow observado, não quantifica amostras
perdidas nem garante que a interpretação do contador foi validada neste módulo.
O volume de logs também pode limitar a aquisição a 115200 baud quando há muitos
eventos de overflow; uma comparação com logs reduzidos é necessária para avaliar
continuidade temporal sem interferência dessa instrumentação.

O FIFO deve produzir aproximadamente 100 registros/s. O instante `ms` é da
leitura; amostras do mesmo bloco compartilham esse instante. `capture.py` preserva
bytes originais, linhas interpretadas, horários de recebimento, metadados e hash.
Os horários e sequências não são automaticamente tratados como prova de presença
ou ausência de dedo.

## Compilação, gravação e captura

Executar pela raiz desta pasta, sempre usando job-guard para compilação, gravação
e coleta. O firmware original deve ser preservado antes de substituir a aplicação.

```bash
job-guard submit --name build-max-test --cwd "$PWD" -- pio run
job-guard submit --name upload-max-test --cwd "$PWD" -- pio run --target upload --upload-port /dev/ttyUSB0
job-guard submit --name capture-max-test --cwd "$PWD" -- python3 capture.py --duration 120
```

A captura abre a serial uma vez e mantém a conexão por 120 segundos. A abertura
pode reiniciar esta placa; a montagem deve conseguir iniciar nessa condição.
Alternar dedo imóvel e ausência de dedo por cerca de 10–15 segundos, anotando os
momentos. Evitar pressionar excessivamente ou movimentar o sensor durante cada
trecho. A finalidade é verificar resposta óptica e continuidade da aquisição,
não validar uma medição clínica.

`logs/` e `.pio/` estão excluídos do Git. O backup da flash fica fora deste projeto,
em diretório privado, pois pode conter credenciais do firmware anterior.

## Resultado da coleta de 13/11/2026

Captura v3: `logs/20261113T163244_060668`, das 16:32:44 às 16:36:44
(America/Belem). A serial foi aberta com a ESP32 fora do soquete e permaneceu
aberta durante a conexão à montagem completa. O usuário confirmou retirada
completa do dedo por pelo menos dez segundos; os instantes individuais não
foram anotados. O estado após fechar a serial não foi observado.

- 23.443 pares vermelho/IR, cobrindo 224,213 s após a conexão do sensor;
  aproximadamente 104,55 registros/s pelo relógio da ESP32.
- IR: 1.495–106.405 contagens; vermelho: 329–28.209. Nenhuma amostra zero
  ou no teto de 18 bits. Há patamares baixos de aproximadamente 1,6–1,9 mil
  no IR e altos de 75–106 mil, compatíveis com a alternância relatada.
- Uma inicialização da ESP32, sem reinícios adicionais registrados.
  Cinco erros I²C ocorreram antes da primeira amostra; nenhum depois.
- 9.484 eventos de contador de overflow não nulo; 16.069 amostras receberam
  `gap=true`. Isso não equivale a 9.484 ou 16.069 amostras perdidas.
  Não se validou continuidade temporal nem cálculo de BPM/SpO₂.
- O limiar de 50.000 do código original separa os patamares observados.
  O sensor responde opticamente neste ensaio; IR sempre zero no projeto
  completo não pode ser atribuído apenas à ausência de dedo ou a um sensor
  totalmente inoperante. A causa exata da falha integrada continua aberta.

Tentativas anteriores preservadas em `logs/`: v1 bloqueou a aquisição por uma
validação excessivamente restritiva criada neste teste (`0x50` versus `0x5F`);
v2 corrigiu essa validação, mas reinicializava a cada contador de overflow
não nulo. v3 registra o contador e lê o conteúdo disponível com marcação.
Essas falhas do teste não são evidência de defeito físico do módulo.

Próximo controle recomendado: repetir com registro serial reduzido ou maior
baudrate, mantendo o restante constante, para distinguir atraso causado pelo
log de comportamento do FIFO/módulo. Depois comparar a aquisição direta e o
driver original no mesmo barramento e frequência, e reintegrar MPU/rede
separadamente. Esta coleta mudou simultaneamente o leitor, a carga de trabalho
e a frequência I²C, portanto não isola qual dessas diferenças resolveu IR=0.

`analysis.json` contém estatísticas, `events.jsonl` as linhas com horário do
computador, `serial.bin` os bytes originais e `optical_response.png` o gráfico.
A captura terminou com uma linha parcial de 60 bytes, preservada nos bytes
originais e excluída das estatísticas de linhas completas. Para reproduzir:

```bash
job-guard submit --name analyze-max --cwd "$PWD" -- python3 analyze.py logs/20261113T163244_060668
```

Compilação/gravação v3 verificadas pelo PlatformIO/esptool. Persiste o aviso
de redefinição de `I2C_BUFFER_LENGTH` no driver reaproveitado; o leitor
direto usa no máximo 30 bytes por transação. Ao final desse ensaio, o teste MAX estava gravado; posteriormente foi substituído
pelo teste MPU. O firmware original foi preservado em backup privado de 4 MB.

## Ambiente e arquivos locais

Requer PlatformIO CLI (`pio` no PATH) para o firmware e Python 3.9+ com
`pyserial` para a captura. Os coletores usam recursos POSIX; foram testados em
Linux. Instale `matplotlib` para gerar os gráficos. Os comandos acima usam
`job-guard`, o limitador de recursos do ambiente de desenvolvimento; em outros
ambientes, execute o comando após `--` diretamente, dentro desta pasta.

As capturas citadas nos resultados são evidências locais não distribuídas no
Git. Os analisadores podem ser utilizados com novas capturas no mesmo formato.
