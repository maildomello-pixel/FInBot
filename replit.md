# FinBot - Telegram Financial Management Bot

## Overview

FinBot is a comprehensive personal finance management bot built for Telegram. It provides users with the ability to track income, expenses, fixed costs, and meal vouchers through both natural language processing and structured commands. The bot includes advanced features like financial reporting, budget tracking, savings goals, visual charts, and automated reminders. It leverages Google Gemini AI for intelligent transaction parsing and offers export capabilities to PDF and Excel formats.

## User Preferences

Preferred communication style: Simple, everyday language.

## System Architecture

### Application Architecture

**Framework**: Python-based Telegram bot using python-telegram-bot library (v20.7)
- **Rationale**: The python-telegram-bot library provides robust async/await support and comprehensive Telegram API coverage
- **Key Pattern**: Event-driven architecture with command handlers and callback query handlers for interactive button responses
- **State Management**: In-memory conversation state tracking for multi-step flows (e.g., categorization, date selection)

### Data Storage

**Database**: SQLite3 with file-based persistence
- **Rationale**: Lightweight, serverless solution suitable for single-user or small-scale deployments without external database dependencies
- **Schema Design**: Transactional data model with tables for:
  - Financial transactions (income, expenses, fixed costs)
  - Savings goals with progress tracking
  - Custom categories
  - Budget limits (monthly and category-based)
  - Recurring payments
  - Reminders
- **Alternative Considered**: PostgreSQL for multi-user scalability (may be added later)

### Natural Language Processing

**AI Integration**: Google Gemini API (optional)
- **Purpose**: Parse natural language transaction descriptions to extract amount, category, and date
- **Fallback**: System operates without AI using structured commands when GEMINI_API_KEY is not configured
- **API Client**: httpx for async HTTP requests to Gemini endpoints

### User Interaction Patterns

**Conversational Flow Design**:
1. **Multi-step Transactions**: User inputs amount → Bot presents category buttons → User selects category → Bot asks for date → Transaction saved
2. **Interactive Buttons**: InlineKeyboardMarkup for category selection, confirmation dialogs, and navigation
3. **Command-based Operations**: Structured commands for advanced features (e.g., `/addmeta`, `/orcamento`)

**Key Design Decision**: Date input occurs AFTER category selection to improve user experience and reduce cognitive load

### Reporting & Visualization

**Export Capabilities**:
- **PDF Generation**: fpdf2 library for detailed financial reports
- **Excel Export**: openpyxl for spreadsheet data export
- **Visual Charts**: matplotlib for pie charts (expense distribution) and line charts (monthly trends)

**Image Processing**: Pillow library for chart rendering and image manipulation

### Date Processing

**Library**: dateparser with Portuguese locale support
- **Flexibility**: Accepts various date formats including relative dates ("ontem", "semana passada")
- **Fallback**: Locale configuration attempts pt_BR.UTF-8 with graceful degradation

### Financial Methods

**Método Traz Paz (MTP)**: Built-in financial planning methodology
- **Purpose**: Structured approach to allocating income across savings, investments, and expenses
- **Implementation**: Calculation algorithms for budget distribution based on MTP principles

## External Dependencies

### Required Services

1. **Telegram Bot API**
   - Environment Variable: `TELEGRAM_BOT_TOKEN`
   - Purpose: Core bot functionality and message handling
   - Obtain via: @BotFather on Telegram

2. **Google Gemini API** (Optional)
   - Environment Variable: `GEMINI_API_KEY`
   - Purpose: Natural language transaction parsing
   - Obtain via: https://makersuite.google.com/app/apikey
   - Fallback: Bot operates with structured commands when unavailable

### Python Libraries

**Core Dependencies**:
- `python-telegram-bot==20.7` - Telegram bot framework
- `httpx==0.25.2` - Async HTTP client for Gemini API
- `dateparser==1.2.0` - Flexible date parsing with locale support
- `matplotlib==3.8.2` - Chart generation
- `pandas==2.1.4` - Data manipulation for reports
- `fpdf2==2.7.9` - PDF report generation
- `openpyxl==3.1.2` - Excel file creation
- `Pillow==10.1.0` - Image processing for charts

### Platform Considerations

**Deployment Environment**: Designed for Replit deployment
- File-based SQLite database for persistence
- Environment variables for sensitive credentials
- No external database server required
- Async runtime support for concurrent user interactions