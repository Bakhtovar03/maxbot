import asyncio
from typing import Any
import re
import aiohttp
import logging
import pprint
from config.config import load_config

config = load_config()

BASE_URL = "https://api.moyklass.com/v1/company"


logger = logging.getLogger(__name__)


# HTTP CLIENT
async def fetch_json(
    session: aiohttp.ClientSession,
    url: str,
    access_token: str,
    **kwargs,
) -> dict[str, Any]:
    """
    Выполняет GET-запрос и возвращает JSON.
    """

    async with session.get(
        url,
        headers={"x-access-token": access_token},
        **kwargs
    ) as resp:

        # проверка HTTP статуса
        if resp.status != 200:
            text = await resp.text()
            logger.error("HTTP %s | %s | %s", resp.status, url, text)
            raise RuntimeError(f"{resp.status}: {text}")

        return await resp.json()

# -------------------------
# TRANSFORMS
def normalize_attributes(attributes: list[dict]) -> dict[str, Any]:
    """
    Преобразует список атрибутов в словарь для удобного доступа.
    """
    return {a["attributeAlias"]: a["value"] for a in attributes}


def extract_course_ids(joins: list[dict]) -> list[int]:
    """
    Извлекает уникальные ID курсов из joins.
    """
    return list({j["courseId"] for j in joins if j.get("courseId")})


def attach_subscriptions(student: dict, subscriptions: dict | None) -> None:
    """
    Добавляет подписки к курсам студента (если есть).
    """

    if not subscriptions:
        return

    student['subscript_totalItems']=subscriptions['stats']['totalItems']

    # courseId -> subscription (для быстрого доступа O(1))
    sub_map = {
        cid: sub
        for sub in subscriptions.get("subscriptions", []) #значение = объект подписки (sub)
        for cid in sub.get("courseIds", [])     #ключ = ID курса (cid)
    }

    # добавляем подписку в курс, если совпадает id
    for course in student.get("courses_data", []):
        cid = course.get("id")
        if cid in sub_map:
            course["subscription"] = {
                "id": sub_map[cid].get("id"),
                "price": sub_map[cid].get("price"),
                "payed":sub_map[cid].get("payed"),
                'visitCount':sub_map[cid].get("visitCount"),
                "visitedCount":sub_map[cid].get("visitedCount"),
                'status':sub_map[cid].get("statusId"),
            }

# -------------------------
# API LAYER
async def get_user(session: aiohttp.ClientSession, student_id: int,access_token) -> dict:
    """Получает данные пользователя по ID."""
    return await fetch_json(session, f"{BASE_URL}/users/{student_id}",access_token=access_token)


async def get_joins(session: aiohttp.ClientSession, student_id: int,access_token:str) -> dict:
    """Получает записи пользователя на курсы (joins)."""
    return await fetch_json(
        session,
        f"{BASE_URL}/joins",
        params={"userId": student_id, "statusId": 2},
        access_token=access_token
    )


async def get_subscriptions(
    session: aiohttp.ClientSession,
    student_id: int,
    access_token: str
) -> dict | None:
    """Получает активные подписки пользователя."""

    data = await fetch_json(
        session,
        f"{BASE_URL}/userSubscriptions",
        access_token=access_token,
        params={"userId": student_id,'statusId':2},
    )
    return data or None


async def get_course(session: aiohttp.ClientSession, course_id: int,access_token) -> dict | None:
    """
    Получает один курс по ID.
    API возвращает список → берём первый элемент.
    """

    data = await fetch_json(
        session,
        f"{BASE_URL}/courses",
        params={"courseId": course_id, "includeClasses": "true"},
        access_token=access_token
    )

    if not data:
        return None

    c = data[0]

    return {
        "id": c.get("id"),
        "course_name": c.get("name"),
        "course_type": c.get("courseType"),
    }


async def get_courses(
    session: aiohttp.ClientSession,
    course_ids: list[int],
    access_token: str
) -> list[dict]:
    """
    Загружает курсы параллельно (asyncio.gather).
    """

    tasks = [get_course(session, cid,access_token=access_token) for cid in course_ids]

    # return_exceptions=True чтобы не падать при одной ошибке
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # фильтруем только успешные ответы
    return [r for r in results if isinstance(r, dict)]

# -------------------------
# DOMAIN
def build_student(user: dict) -> dict:
    """
    Приводит raw user из API к структуре студента.
    """

    attrs = normalize_attributes(user.get("attributes", []))

    return {
        "id": user.get("id"),
        "name": user.get("name"),
        "email": user.get("email"),
        "phone": user.get("phone"),

        # данные из attributes
        "parent": attrs.get("parent1"),
        "birthday": attrs.get("birthday"),

        "filials": user.get("filials", []),
    }
async def get_achievements(session: aiohttp.ClientSession, student_id: int,access_token) -> dict[str, list[str]]:
    """Загружаем дипломы и зачеты"""

    certificates =[]
    passes =[]
    response = await fetch_json(
        session,
        f"{BASE_URL}/userComments",
        params={"userId": student_id},
        access_token=access_token
    )
    for res in response['userComments']:
        comment = res["comment"]
        if 'диплом' in comment.lower():
            comment = re.sub(r"\s+", " ", comment).strip()
            certificates.append(comment)
        if 'зачет' in comment.lower():
            comment = re.sub(r"\s+", " ", comment).strip()
            passes.append(comment)

    return {'certificates': certificates, 'passes': passes}

# -------------------------
# финальная функция
async def get_student(student_id: int) -> dict | None:
    """
    Основной сценарий:
    собирает студента из разных API запросов.
    """

    logger.info("START student=%s", student_id)

    async with aiohttp.ClientSession() as session:

        async with session.post(
                f"{BASE_URL}/auth/getToken",
                json={'apiKey':config.apiKey}

        ) as resp:
            resp = await resp.json()
            access_token = resp['accessToken']
        # пользователь
        try:
            user = await get_user(session, student_id,access_token=access_token)
        except Exception as e:
            return None

        # записи на курсы
        joins = await get_joins(session, student_id,access_token=access_token)

        student = build_student(user)

        # получаем список ID курсов
        course_ids = extract_course_ids(joins.get("joins", []))

        # загружаем курсы
        student["courses_data"] = await get_courses(session, course_ids,access_token=access_token)

        # подписки и привязка к курсам
        subscriptions = await get_subscriptions(session, student_id,access_token=access_token)
        attach_subscriptions(student, subscriptions)
        achievements = await get_achievements(session, student_id,access_token=access_token)
        student["achievements"] = achievements
        logger.info("DONE student=%s", student_id)
        return student

# -------------------------
# RUN
if __name__ == "__main__":
    result = asyncio.run(get_student(4047194))
    pprint.pprint(result)