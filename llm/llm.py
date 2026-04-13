import os
import yaml
import asyncio
from concurrent.futures import ThreadPoolExecutor

from environs import Env
from gigachat import GigaChat

from langchain_core.documents import Document
from langchain_community.embeddings import GigaChatEmbeddings
from langchain_community.vectorstores import FAISS

from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnableLambda, RunnableParallel, RunnableWithMessageHistory

from langchain_redis import RedisChatMessageHistory
from redis import Redis

# Импорт промптов из внешнего файла
from lexicon.lexicon import PROMPT_LEXICON

# ============================================================
# 1. ИНИЦИАЛИЗАЦИЯ GIGACHAT
# ============================================================

env = Env()
env.read_env()

GIGA_KEY = env.str("GIGACHAT_KEY")

# Синхронный клиент GigaChat
giga = GigaChat(
    #model='GigaChat-2-Pro',
    credentials=GIGA_KEY,
    verify_ssl_certs=False,
)

# ThreadPool для async вызовов
executor = ThreadPoolExecutor(max_workers=10)

async def giga_invoke_async(prompt_text: str) -> str:
    """Асинхронный вызов GigaChat"""
    loop = asyncio.get_event_loop()
    response = await loop.run_in_executor(executor, giga.chat, prompt_text)
    return response.choices[0].message.content


# ============================================================
# 2. ЗАГРУЗКА YAML
# ============================================================

with open("LLM/rag.yaml", "r", encoding="utf-8") as f:
    data = yaml.safe_load(f)

all_docs = []

# -------- COURSES --------
for course in data["COURSES"]:

    # Формируем понятный текст для LLM
    text = f"""
Курс: {course['title']}
Возраст: {course['age_min']} - {course['age_max']}

Когда подходит:
{course['when_to_offer']}

Описание:
{course['description']}

Что освоит:
{", ".join(course['skills'])}

Результат для ребенка:
{", ".join(course['child_outcomes'])}

Польза для родителя:
{", ".join(course['parent_value'])}
"""

    # Добавляем в векторную базу
    all_docs.append(
        Document(
            page_content=text,
            metadata={
                "type": "course",
                "id": course["id"],
                "age_min": course["age_min"],
                "age_max": course["age_max"],
                "tags": course.get("tags", []),
            }
        )
    )

# -------- ENTITY --------
entity = data["ENTITY"]

group_format_text = "\n".join(f"- {item}" for item in entity['GROUP_FORMAT'])

branch_texts = []
for city, branches in entity['BRANCHES'].items():
    for b in branches:
        directions = ", ".join(b.get("directions", []))
        branch_texts.append(f"Район {b['district']} - {b['address']} ({directions})")
branches_info = " || ".join(branch_texts)

entity_text = f"""
Школа: {entity['name_ru']}
Тип: {entity['type']}
Возраст: {entity['age_range']}
Формат занятий:
{group_format_text}
Опыт: {entity['experience']}
Описание:
{entity['description']}

Адреса филиалов: {branches_info}
"""


all_docs.append(Document(page_content=entity_text, metadata={"type": "entity"}))

# -------- POLICY --------
policy = data["POLICY"]

policy_text = f"""
Пробное занятие: {policy['trial_lesson']}
Запись: {policy['recording']}
"""

all_docs.append(Document(page_content=policy_text, metadata={"type": "policy"}))


# ============================================================
# 3. FAISS
# ============================================================

embeddings = GigaChatEmbeddings(
    credentials=GIGA_KEY,
    verify_ssl_certs=False
)

index_path = "LLM/faiss_yaml"

if os.path.exists(index_path):
    db = FAISS.load_local(index_path, embeddings, allow_dangerous_deserialization=True)
else:
    db = FAISS.from_documents(all_docs, embeddings)
    db.save_local(index_path)

retriever = db.as_retriever(
    search_type="mmr",
    search_kwargs={"k": 4}
)


# ============================================================
# 4. REDIS
# ============================================================
redis_host = os.getenv("REDIS_HOST", "redis")
redis_port = int(os.getenv("REDIS_PORT", 6379))
redis_client = Redis(host=redis_host, port=redis_port, db=0)


def get_redis_history(session_id: str):
    return RedisChatMessageHistory(
        redis_client=redis_client,
        session_id=session_id,
        ttl=3600,
    )


# ============================================================
# 5. ПРОМПТ (ИЗ LEXICON)
# ============================================================

prompt = ChatPromptTemplate.from_messages([
    ("system", PROMPT_LEXICON["system_policy"]),
    ("system", PROMPT_LEXICON["rag_guard"]),
    ("system", PROMPT_LEXICON["assistant_template"]),
    MessagesPlaceholder(variable_name="history"),
    ("user", "{question}")
])


# ============================================================
# 6. RAG
# ============================================================

# Склеиваем документы в строку

def format_docs(docs):
    return "\n\n".join(d.page_content for d in docs)


rag_chain = (
    RunnableParallel({
        "question": RunnableLambda(lambda x: x["question"]),

        # Получаем релевантные документы
        "context": RunnableLambda(lambda x: retriever.invoke(x["question"]))
                   | RunnableLambda(format_docs),

        # Берём последние сообщения
        "history": RunnableLambda(lambda x: x.get("history", [])[-6:])
    })
    | prompt
    | RunnableLambda(lambda msg: msg.to_string())
    | RunnableLambda(lambda text: asyncio.run(giga_invoke_async(text)))
    | StrOutputParser()
)


# Оборачиваем в историю
chain_with_history = RunnableWithMessageHistory(
    rag_chain,
    get_session_history=get_redis_history,
    input_messages_key="question",
    history_messages_key="history"
)


# ============================================================
# 7. API
# ============================================================

async def ask_giga_chat_async(user_question: str, session_id: str) -> str:
    """Асинхронный вызов AI"""
    return await chain_with_history.ainvoke(
        {"question": user_question},
        config={"configurable": {"session_id": session_id}}
    )
