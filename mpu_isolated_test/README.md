# Teste isolado do acelerômetro

Acessa somente os endereços 0x68/0x69 por SDA21/SCL22, inicialmente a 100 kHz.
Não inicializa Wi-Fi, MQTT, MAX30102, NTC, botão nem motor. Na montagem completa,
o isolamento é de software: alimentação e barramento continuam compartilhados.

Reaproveita o procedimento do projeto de procurar o módulo em 0x68/0x69 e ler
14 bytes a partir de 0x3B. A implementação foi reescrita para verificar todas as
transações, configurar explicitamente o sensor e decodificar os bytes em ordem
definida. Não há compensação de offset ou calibração que possa esconder um eixo
preso no limite. A aplicação integrada em `wearable_esp32/` não é alterada.

## Configuração e interpretação

- Serial 230400 baud. Aquisição inicial a 50 Hz, ±2 g, sem FIFO e sem DMP.
- WHO_AM_I 0x68: mapa MPU6050; 0x70: mapa MPU6500; 0x69: compatibilidade herdada
  do projeto, identidade não padrão, sem afirmar modelo/autenticidade.
- Reset do sensor, eixos habilitados, PLL, filtro configurado, divisor de taxa,
  faixa, interrupção data-ready e leitura de retorno dos bits relevantes.
  Em 0x70, ACCEL_CONFIG2 também é configurado explicitamente.
- A escala é conferida antes de cada amostra. Leitura curta ou faixa inesperada
  não produz uma amostra convertida. Configuração completa é revista a cada segundo.
- Sensibilidades: 16384, 8192, 4096 e 2048 LSB/g para ±2, ±4, ±8 e ±16 g.
- `raw` contém inteiros assinados; `g` contém eixos em g; `norm` é a norma.
  Parado, espera-se norma próxima de 1 g, pois a gravidade está incluída.
- `fresh` informa o bit data-ready observado antes da leitura. `false` pode
  indicar repetição; esta coleta por temporização não promete amostras sem perdas.
- `rails` conta valores exatamente -32768 ou +32767 por eixo na janela.
- `epoch` muda na reconfiguração ou troca de método de leitura. Comparações de
  faixas devem separar épocas e aguardar acomodação após o reset do sensor.
- `read axis` usa três transações de dois bytes: útil parado, sem simultaneidade
  garantida entre eixos. A leitura padrão por bloco mantém o agrupamento do sensor.
- Temperatura do chip e giroscópio não são convertidos. `probe` permite examinar
  todos os 14 bytes sem depender de uma configuração considerada válida.

## Comandos sem regravar ou reabrir a serial

Uma linha terminada em LF: `dump`, `probe`, `reinit`, `range 2`, `range 4`,
`range 8`, `range 16`, `rate 10`, `rate 25`, `rate 50`, `clock 100`, `clock 400`,
`read axis`, `read burst`, `stream off`, `stream on`.

Faixa, taxa e clock provocam reconfiguração/reset somente do sensor. Não alteram
flash nem reiniciam a ESP32. Valores inválidos são rejeitados. Com `stream off`,
continua a aquisição e o resumo por segundo, reduzindo tráfego serial.

`capture.py` abre a porta uma única vez, com DTR/RTS falsos antes da abertura,
e mantém um arquivo `commands.jsonl` no diretório da coleta. Adicionar uma linha
JSON envia o comando pela conexão já aberta; comandos antigos não são repetidos.
Exemplo: `{"command":"range 8","note":"Comparação da escala, montagem parada"}`.
Uma linha `{"marker":"movimento iniciado"}` só marca o log, sem comando à placa.
`command_result` confirma aceitação; `config` confirma reconfiguração bem-sucedida.
É necessário observar ambos, pois aceitar um comando não garante comunicação I²C.

## Revisão antes da gravação

`tests/firmware_test.cpp` compila o próprio `src/main.cpp` com interfaces simuladas
de Arduino/Wire. Valida todos os padrões de 16 bits, escala de 1 g nas quatro
faixas, detecção de saturação, endereço alternativo, identidades suportadas,
recuperação de ausência, leitura incompleta, divergência de configuração, método
por eixo e parser de comandos. Executado com AddressSanitizer e UBSan.
`tests/capture_test.py` exercita o coletor real em pseudoterminal, incluindo envio
de comando sem reabertura. Esses resultados são simulações, não leituras físicas.

Para repetir esses testes em Linux, com `g++` e `pyserial` instalados:

```bash
job-guard submit --name test-mpu-build --cwd "$PWD" -- g++ -std=c++17 -Wall -Wextra -fsanitize=address,undefined -fno-omit-frame-pointer -g -Itests/fakes tests/firmware_test.cpp -o tests/firmware_test
```

Após a compilação terminar, execute `tests/firmware_test` nesta pasta. Para o
teste da captura, que usa um pseudoterminal e não acessa a ESP32:

```bash
job-guard submit --name test-mpu-capture --cwd "$PWD" -- python3 tests/capture_test.py
```

Compilar, gravar e coletar sempre por `job-guard`:

```bash
job-guard submit --name build-mpu --cwd "$PWD" -- pio run
job-guard submit --name upload-mpu --cwd "$PWD" -- pio run --target upload --upload-port /dev/ttyUSB0
job-guard submit --name capture-mpu --cwd "$PWD" -- python3 capture.py --duration 600
```

## Ensaio físico

Abrir a serial e verificar firmware/comandos com a ESP32 fora do soquete, antes
de conectar a montagem. Manter a mesma conexão durante o ensaio. Começar parado;
depois orientar lentamente o conjunto em posições diferentes, parando em cada
uma. Não é necessário deixar cair ou bater a montagem. Se houver eixo saturado,
comparar faixas e métodos de leitura antes de concluir defeito físico.

Logs preservam bytes, linhas, horários de recebimento, comandos e metadados.
Horários da ESP32 são de leitura; movimentos reais só são rotulados quando
informados. O backup integral do firmware original permanece no diretório privado
do diagnóstico anterior; o teste MAX30102 permanece em sua própria pasta.

Referências: mapas de registradores InvenSense
[MPU6050](https://www.invensense.com/wp-content/uploads/2015/02/MPU-6000-Register-Map1.pdf)
e [MPU6500, revisão 2.1, cópia do documento do fabricante](https://www.ic-components.se/files/5b/MPU-6500.pdf).

## Resultado físico de 13/11/2026

Uma única gravação física, job `20261113-164926-657d9a10`, após repetir os testes
do firmware final. Captura `logs/20261113T165028_694408`, 16:50:28–17:00:28,
America/Belem, 600,028 s. Inicialmente ESP32 standalone; depois na montagem
completa, com a mesma serial aberta. O usuário informou montagem parada.

O módulo respondeu em 0x68 com WHO_AM_I 0x70. Houve três inicializações com
configuração lida e verificada, todas ±2 g/16384 LSB/g, 50 Hz e I²C a 100 kHz.
Foram recebidas 308 amostras em três trechos curtos (90, 179 e 39 amostras),
entre 16:57:26 e 16:58:06; isso não representa 40 segundos contínuos de aquisição.

- X bruto = -32768 em **308/308 amostras**, equivalente a -2 g na faixa
  efetivamente verificada. Y e Z variaram; nenhum deles atingiu o limite digital.
- Norma entre 2,33640 e 2,36546 g. O resultado excessivo foi reproduzido com
  leitura e conversão independentes do restante do projeto.
- Todos esses registros apresentaram data-ready. Isso não prova integridade
  elétrica dos bytes; apenas registra o estado observado pelo software.
- A comunicação foi intermitente e houve 402 eventos de erro I²C no total;
  esse total inclui o período standalone e consultas ao endereço alternativo
  0x69 sem resposta. Não são 402 falhas de um sensor conectado e identificado.
- 400 kHz não recuperou a comunicação durante o intervalo testado; voltou-se a
  100 kHz. A comparação ±8 g não chegou a configurar nem coletar dados válidos.
  A última solicitação foi voltar a ±2 g; não houve nova confirmação de configuração.

Tensões informadas pelo usuário, relativas ao GND do módulo: VCC 4,78 V,
SDA 3,08 V, SCL 3,30 V. Pontas aplicadas diretamente aos pinos; o usuário
informou não pressionar voluntariamente fios/soldas. Os horários exatos das
medições não são conhecidos. A recuperação temporária não pode ser atribuída
causalmente ao multímetro ou a pressão mecânica. Essas medidas não comprovam a
tensão interna regulada nem a qualidade dos pulsos.

**Interpretação:** erro de cálculo da norma e simples pressuposição errada de
faixa não explicam, sozinhos, o X bruto no limite neste ensaio. Defeito do módulo,
alimentação interna e montagem/barramento permanecem hipóteses. O ensaio não
separa uma falha do sensor de corrupção de bytes, nem exclui incompatibilidade
com reset/configuração/repeated START usados pelo teste. Não é um diagnóstico
definitivo de defeito físico; também não é uma aquisição aprovada como saudável.

Próximos controles: verificar tensão regulada no módulo e forma dos sinais;
comparar ligação curta somente ESP+MPU ou módulo conhecido funcional; depois
repetir ±8 g e leitura por eixo usando os comandos já disponíveis. Não corrigir
o problema apenas subtraindo 2 g ou calibrando o eixo saturado.

`analysis.json` resume épocas; `events.jsonl` preserva linhas e comandos;
`serial.bin` preserva os bytes; `user_observations.json` separa as medidas
informadas pelo usuário. O boot ROM a 115200 baud gerou texto ilegível na
captura a 230400, concatenado ao JSON inicial do firmware; esse JSON está
preservado no texto bruto, embora não tenha sido contado como evento `boot`.
O estado da placa após fechar a serial não foi observado. Firmware de teste
permaneceu gravado ao final do ensaio, sem Wi-Fi/MQTT.

## Ambiente e arquivos locais

Requer PlatformIO CLI (`pio` no PATH) para o firmware e Python 3.9+ com
`pyserial` para a captura. Os coletores usam recursos POSIX; foram testados em
Linux. Instale `matplotlib` para gerar os gráficos. Os comandos acima usam
`job-guard`, o limitador de recursos do ambiente de desenvolvimento; em outros
ambientes, execute o comando após `--` diretamente, dentro desta pasta.

As capturas citadas nos resultados são evidências locais não distribuídas no
Git. Os analisadores podem ser utilizados com novas capturas no mesmo formato.

## Arquitetura de referência

[Diagrama funcional do acelerômetro](architecture/mpu_architecture.png), com
[gerador em Python](architecture/render.py). Representa caminhos por eixo e
interface I²C compartilhada, com base no
[datasheet MPU6500, seções 4.4 e 4.7](https://product.tdk.com/system/files/dam/doc/product/sensor/mortion-inertial/imu/data_sheet/mpu-6500-datasheet2.pdf).
O identificador observado foi 0x70; isso não comprova autenticidade do chip.
Uma falha interna pode afetar apenas um eixo, mas o ensaio não separou essa
hipótese de problemas de comunicação. Y/Z variarem não comprova calibração:
Z ficou aproximadamente entre -1,26 e -1,21 g na condição informada de repouso.
