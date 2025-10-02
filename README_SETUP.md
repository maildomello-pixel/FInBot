# FinBot - Bot de Gestão Financeira Telegram

## Configuração Necessária

Este bot requer duas variáveis de ambiente (secrets):

### 1. TELEGRAM_BOT_TOKEN
Token do seu bot do Telegram. Obtenha através do @BotFather no Telegram.

### 2. GEMINI_API_KEY (Opcional)
Chave da API do Google Gemini para funcionalidades de IA. Obtenha em https://makersuite.google.com/app/apikey

## Novos Recursos Adicionados

### Correções de Bugs
1. ✅ Data é agora corretamente reconhecida e armazenada no campo data_transacao
2. ✅ Vale-alimentação agora deduz corretamente do saldo quando selecionado

### Novos Comandos

#### Metas de Economia
- `/metas` - Ver todas as metas
- `/addmeta <valor> <nome>` - Criar meta (Ex: /addmeta 5000 Viagem)
- `/progresso_meta <id> <valor>` - Adicionar progresso

#### Gráficos Visuais
- `/grafico` - Gráfico de pizza das despesas
- `/grafico_mensal` - Evolução mensal

#### Lembretes
- `/lembretes` - Ver todos lembretes
- `/addlembrete <dia> <descrição>` - Criar lembrete

#### Categorias Customizadas
- `/categorias` - Ver categorias
- `/addcategoria <nome>` - Adicionar categoria
- `/removecategoria <nome>` - Remover categoria

#### Relatórios Avançados
- `/relatorio_detalhado` - Gerar PDF
- `/relatorio_exportar` - Exportar para Excel

#### Controle de Orçamento
- `/orcamento <valor>` - Definir orçamento mensal
- `/orcamento_categoria <categoria> <valor>` - Orçamento por categoria

#### Pagamentos Recorrentes
- `/recorrentes` - Ver recorrentes
- `/addrecorrente <valor> <dia> <descrição>` - Adicionar recorrente

#### Dashboard
- `/dashboard` - Visão geral completa com alertas inteligentes

## Como Executar

O bot será iniciado automaticamente quando as secrets estiverem configuradas.
