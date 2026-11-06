# Central monitoring dashboard

The central monitoring dashboard is implemented on a Raspberry Pi 3B+ and has two components:

- an **MQTT broker** where the wearable device sensors can publish measurement data;
- and a **Python web server** hosting a [Flask](https://flask.palletsprojects.com/en/stable/) web-application that displays the measured sensor data.

## Setup

```
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Na pasta `server/`, crie a configuração local a partir do modelo:

```bash
cp -n .env.example .env
# Edite .env e preencha MQTT_USERNAME e MQTT_PASSWORD com as credenciais do Mosquitto.
python3 src/main.py
```

O servidor carrega `server/.env` automaticamente, independentemente do diretório
de execução. O arquivo real é ignorado pelo Git; somente `.env.example` é
versionado. Variáveis já exportadas no ambiente têm prioridade sobre o arquivo.
As senhas são lidas literalmente, sem expansão de `${VAR}`. Coloque valores
com espaços ou `#` entre aspas simples. Atualize as dependências com
`pip install -r requirements.txt` antes de iniciar esta versão.

The server connects to the local broker at `127.0.0.1:1883`, subscribes to
`wearable/finger/measurements`, and makes the latest wearable sample available
to the dashboard at `http://<raspberry-pi-ip>:5000`.

The connection can be changed without editing the source code:

```
export MQTT_BROKER="127.0.0.1"
export MQTT_PORT="1883"
export MQTT_TOPIC="wearable/finger/measurements"
export WEB_HOST="0.0.0.0"
export WEB_PORT="5000"
```

## Correções e operação — 06/11/2026

O IP confirmado da Raspberry Pi é `10.197.100.243`. O dashboard fica em
`http://10.197.100.243:5000`. O processo Flask escuta em `0.0.0.0`; o subscriber
usa `127.0.0.1:1883` por padrão porque roda na mesma Raspberry que o Mosquitto.
Se o broker estiver configurado para escutar somente no IP da interface de rede,
configure `MQTT_BROKER=10.197.100.243` também no servidor.

`MQTT_USERNAME`, `MQTT_PASSWORD` e `MQTT_TOPIC` são lidos do ambiente. Não há
usuário/senha fixos no código. Use uma conta existente no Mosquitto com permissão
de leitura do tópico; o wearable precisa de permissão de publicação. O servidor
só sinaliza conexão pronta depois de receber a confirmação da assinatura.

O firmware atual está em `wearable_esp32/wearable_esp32.ino`. Copie
`wearable_esp32/secrets.example.h` para `wearable_esp32/secrets.h` e preencha as
credenciais localmente. O arquivo privado é ignorado pelo Git. A compilação sem
ele usa valores de exemplo, que **não permitem uma conexão real**. O endereço
do broker pode ser substituído por `WEARABLE_MQTT_BROKER` nesse arquivo.

No Serial, a 115200 baud, devem aparecer inicialização, disponibilidade dos
sensores, tentativas de Wi-Fi, IP local, conexão MQTT e tamanho das publicações.
Os códigos MQTT `-2`, `-4`, `4` e `5` indicam, respectivamente, falha TCP,
timeout, credenciais rejeitadas e acesso não autorizado. A publicação ocorre
aproximadamente a cada segundo mesmo sem MPU6050 ou MAX30102.

Para investigar a Raspberry, sem alterar sua configuração:

```bash
systemctl status mosquitto --no-pager
ss -ltnp | grep ':1883'
journalctl -u mosquitto -n 50 --no-pager
```

O listener precisa aceitar conexões da interface acessível pela ESP. Se escutar
somente em `127.0.0.1`, o subscriber local pode funcionar enquanto a ESP não
consegue conectar. Confirme também rede/roteamento, firewall e credenciais.
O teste TCP feito deste computador em 06/11/2026 expirou após 2 segundos;
isso não distingue broker desligado, bloqueio de rede ou listener incorreto.

### Histórico e interface

- As abas, atualização e download do histórico funcionam sem Chart.js. Quando
  o CDN estiver indisponível, aparece uma indicação e os gráficos ficam ausentes.
- `sample_id` identifica cada medição recebida; os snapshots SSE repetidos não
  acrescentam o mesmo lote novamente ao gráfico.
- Os campos atuais ficam vazios quando os dados estão desatualizados ou há
  desconexão. O histórico permanece acessível.
- O caminho padrão do histórico é `server/src/telemetry_history.txt`, independente
  do diretório de execução. `TELEMETRY_LOG_PATH` aceita outro caminho; seu diretório
  deve existir e permitir escrita. Os registros antigos são preservados; os novos
  são JSON por linha, com horário, medição validada e estado de queda calculado.
- Erros de escrita são registrados e indicados na interface, sem encerrar a
  recepção MQTT. A consulta retorna até 200 registros e lê no máximo 2 MiB.
- Timeout e cancelamento de queda são registrados como eventos. A indicação
  visual de alerta não significa acionamento automático de serviço de emergência.

### Verificações reproduzíveis

As dependências de teste ficam em `requirements-test.txt`, separadas das usadas
na Raspberry. Execute instalações, compilação e testes através do `job-guard`:

```bash
job-guard submit --name wearable-build --cwd /CAMINHO/PCS3858-EmbeddedSystemsLab -- pio run -j 2
job-guard submit --name server-tests --cwd /CAMINHO/PCS3858-EmbeddedSystemsLab -- /CAMINHO/venv/bin/python -m pytest -q server/tests
```

Os testes de navegador exigem Chromium instalado pelo Playwright ou a variável
`PLAYWRIGHT_CHROMIUM_EXECUTABLE` apontando para um executável compatível. O teste
nativo do firmware usa `g++` com AddressSanitizer e UndefinedBehaviorSanitizer.
Ele executa o código do sketch com interfaces de hardware simuladas: verifica
publicações sem sensores, lote completo, limite do buffer e cancelamento offline.
Isso não substitui o teste físico dos drivers, do botão, das medidas ou da rede.

As publicações continuam em QoS 0: são dados ao vivo, sem garantia de entrega
ou reprodução de amostras perdidas. A fila mantém apenas a medição mais recente.
O cancelamento pendente é tentado novamente após reconexão, mas o sucesso de
`publish()` não é uma confirmação de recebimento pela aplicação na Raspberry.
O limiar de queda de 0,3 g e o resistor de referência de 20 kΩ foram preservados;
sua adequação ao hardware e calibração permanecem por validar. O histórico cresce
por acréscimo; a política de arquivamento/retensão ainda deve ser definida.

### Evidência local da revisão

Em 06/11/2026, 25 casos passaram em 9,97 segundos: validação atômica de mensagens,
temperatura inválida, ausência de MPU, timeout/cancelamento de queda, erro de
escrita do histórico, assinatura recusada, mensagens retidas/malformadas,
broker local com autenticação e reconexão, SSE, abas/refresh/download em Chromium,
CDN indisponível, deduplicação de lotes e execução nativa do sketch com sensores
ausentes. O broker de teste foi AMQTT; não foi o Mosquitto da Raspberry.

A compilação PlatformIO para `esp32dev`/Arduino ESP32 2.0.17 passou: 52.516 bytes
de RAM estática e 782.129 bytes de flash. Esses números não incluem a memória
dinâmica das tarefas, filas e conexões. Permanece um aviso preexistente sobre a
redefinição de `I2C_BUFFER_LENGTH` em `MAX30105.h`. Não houve upload para ESP
ou alteração remota na Raspberry. A integração Git foi autorizada após a
apresentação desses resultados; o teste físico permanece pendente.
