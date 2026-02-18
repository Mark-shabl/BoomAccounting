# Boom WebUI

Веб-интерфейс для локального запуска LLM-моделей в формате GGUF. Регистрация, скачивание моделей с Hugging Face, чаты со стримингом ответов.

## Возможности

- **Регистрация и авторизация** — JWT, хранение токена в localStorage
- **Модели** — поиск и скачивание GGUF с Hugging Face в локальный volume
- **Чаты** — создание чатов, обмен сообщениями, стриминг ответов через SSE
- **Настройки генерации** — temperature, max_tokens, top_p, top_k, repeat_penalty, system prompt
- **Управление чатами** — удаление чатов

## Стек

| Компонент | Технологии |
|-----------|------------|
| Backend | FastAPI, SQLAlchemy, Alembic, JWT |
| БД | MariaDB |
| LLM | llama-cpp-python (llama.cpp) |
| Frontend | React 19, Vite, TypeScript |
| Инфра | Docker Compose |

## Быстрый старт

### 1. Клонирование и настройка

```bash
git clone <repo-url>
cd BoomAccounting
```

### 2. Переменные окружения

Создай `.env` в корне проекта:

```env
# MariaDB
MARIADB_DATABASE=boom
MARIADB_USER=boom
MARIADB_PASSWORD=boom
MARIADB_ROOT_PASSWORD=boomroot

# JWT (обязательно смени в продакшене)
JWT_SECRET=your-secret-key-min-32-chars

# Hugging Face (для приватных репозиториев)
HF_TOKEN=
```

### 3. Запуск

```bash
docker compose up --build
```

Первый запуск может занять несколько минут (сборка backend с llama-cpp-python).

### 4. Доступ

- **Приложение**: http://localhost:5173
- **API docs**: http://localhost:8000/docs
- **Health check**: http://localhost:8000/health

### 5. Первые шаги

1. Зарегистрируйся (Register)
2. Войди (Login)
3. На странице Models — выбери модель и нажми Download
4. Дождись окончания загрузки
5. Перейди в Chat — создай чат и начни общение

## Структура проекта

```
BoomAccounting/
├── backend/           # FastAPI приложение
│   ├── app/
│   │   ├── api/       # Роуты: auth, models, chats, hf
│   │   ├── core/      # Конфиг, security
│   │   ├── db/        # Модели, сессия
│   │   ├── schemas/   # Pydantic-схемы
│   │   └── services/  # llm_runner, hf_downloader
│   ├── alembic/       # Миграции БД
│   └── requirements.txt
├── frontend/          # React приложение
│   └── src/
│       ├── pages/     # Login, Register, Models, Chat
│       └── lib/       # api, sse
├── docker-compose.yml
└── .env
```

## API

| Метод | Путь | Описание |
|-------|------|----------|
| POST | `/auth/register` | Регистрация |
| POST | `/auth/login` | Вход |
| GET | `/auth/me` | Текущий пользователь |
| GET | `/models` | Список моделей пользователя |
| POST | `/models` | Добавить модель (скачать) |
| GET | `/chats` | Список чатов |
| POST | `/chats` | Создать чат |
| POST | `/chats/remove` | Удалить чат (body: `{ chat_id }`) |
| GET | `/chats/{id}` | Детали чата с сообщениями |
| POST | `/chats/{id}/messages` | Отправить сообщение |
| GET | `/chats/{id}/stream` | SSE-стрим ответа модели |

## Разработка

### Локальный запуск без Docker

**Backend:**
```bash
cd backend
python -m venv .venv
.venv\Scripts\activate   # Windows
pip install -r requirements.txt
# Настрой DATABASE_URL, JWT_SECRET в .env
uvicorn app.main:app --reload
```

**Frontend:**
```bash
cd frontend
npm install
npm run dev
```

При локальном запуске frontend использует прокси `/api` → `http://localhost:8000`.

### Миграции БД

```bash
docker compose exec -e PYTHONPATH=/app backend alembic upgrade head
```

### Пересборка backend

```bash
docker compose build backend --no-cache
docker compose up -d backend
```

## Решение проблем

| Проблема | Решение |
|---------|---------|
| 500 при открытии чата | Выполни `alembic upgrade head` |
| Failed to fetch | Проверь, что backend запущен (`docker compose ps`) |
| Method Not Allowed | Убедись, что backend перезапущен после изменений |
| Модель не скачивается | Проверь HF_TOKEN для приватных репозиториев |
| Медленная первая генерация | llama.cpp загружает модель в память при первом запросе |

## Лицензия

MIT
