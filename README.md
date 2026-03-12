# 🛩️ Aviator Scraper

Scraper Python que monitora o jogo **Aviator** no `br4.bet.br` em tempo real e envia cada nova vela para um webhook N8N.

---

## 📁 Estrutura

```
aviator-scraper/
├── scraper.py          ← Script principal
├── requirements.txt    ← Dependências Python
├── .env                ← Suas credenciais (já preenchido)
├── .env.example        ← Template de referência
└── README.md           ← Este arquivo
```

---

## ⚙️ Instalação

### 1. Instalar Python 3.10+
Baixe em: https://www.python.org/downloads/

### 2. Instalar dependências
```bash
cd aviator-scraper
pip install -r requirements.txt
```

### 3. Verificar o `.env`
O arquivo `.env` já está configurado com suas credenciais e o webhook.
Edite se precisar trocar alguma coisa:
```
CASINO_EMAIL=joacygoncalves4@gmail.com
CASINO_PASSWORD=12386510Br$
WEBHOOK_URL=https://n8n.linikrodrigues.com.br/webhook/velas-n8n-scraper
POLL_INTERVAL=2
```

---

## ▶️ Como Rodar

```bash
python scraper.py
```

O Chrome vai abrir automaticamente, fazer login e começar a monitorar.  
Cada nova vela aparece no console e é enviada ao webhook:

```
2026-03-12 14:30:01 [INFO] ✅ Vela enviada: 2.16x  (total: 1)
2026-03-12 14:31:45 [INFO] 🕯️  Nova vela detectada: 5.88x
2026-03-12 14:31:45 [INFO] ✅ Vela enviada: 5.88x  (total: 2)
```

---

## 📤 Payload do Webhook

Cada vela envia um `POST` JSON para o N8N:

```json
{
  "multiplier": 2.16,
  "timestamp": "2026-03-12T14:30:01",
  "source": "aviator-scraper"
}
```

---

## 🔄 Rodando 24/7

O script já tem **auto-restart** interno. Se cair por qualquer razão, reinicia em 30 segundos automaticamente.

### Opção A — Rodar em segundo plano (Windows)
```bash
pythonw scraper.py
```

### Opção B — Agendador de Tarefas do Windows
1. Abra o **Agendador de Tarefas**
2. Criar tarefa → Disparador: "Ao inicializar sistema"
3. Ação: `python C:\caminho\para\scraper.py`

### Opção C — Em servidor/VPS Linux (mais recomendado)
```bash
nohup python scraper.py > scraper.log 2>&1 &
```

---

## 🗒️ Logs

Os logs são salvos em `aviator_scraper.log` na mesma pasta.

---

## ⚠️ Notas Importantes

- O Chrome precisa estar instalado no computador
- `undetected-chromedriver` baixa o ChromeDriver automaticamente
- O modo headless (sem janela) pode ser ativado descomentando a linha no `scraper.py`
