from typing import Any

from maxo.routing.filters import BaseFilter
from maxo.routing.ctx import Ctx
from maxo.routing.updates.message_created import MessageCreated


class IsAdmin(BaseFilter[MessageCreated]):
    def __init__(self,admin_list: list[int],redis_set=None):
        self.admin_list = set(admin_list)
        self.redis_set = redis_set

    async def __call__(self, update: MessageCreated, ctx: Ctx) -> bool:
        redis_client = ctx.get("redis_client")
        user_id = update.message.sender.user_id if update.message.sender else None
        if user_id in self.admin_list:
            return True
        if self.redis_set and redis_client is not None and user_id is not None:
            try:
                is_admin = await redis_client.sismember(
                    self.redis_set,
                    user_id,
                )
                return is_admin
            except Exception as e:  # noqa: BLE001
                print(f"Redis error {e}")
                return False
        return False



def normalize_info(data:dict[str,Any]) -> str:

    name = data["name"].split(" ")
    first_name = name[0]
    last_name = name[1]

    courses =[]
    certificates =''
    passes =''
    for course in data["courses_data"]:
        normalize_course =(f'\n<b>Название курса:</b>\n'
                           f'\n{course['course_name']}\n'
                           )
        if  'subscription' in course:
            normalize_course +=(
                            f'Цена:\n{course["subscription"]['price']}\n'
                            f'Количество оплаченных занятий по абонементу:'
                            f'\n{course['subscription']["visitCount"]}\n'
                            f'Количество посещенных занятий:'
                            f'\n{course['subscription']["visitedCount"]}\n\n')
        else:
            normalize_course +=f'\n⚠️Абонемент истёк⚠️\n'
        courses.append(normalize_course)



    for achievements in data["achievements"]['certificates']:
        certificates += achievements + '\n'

    for achievements in data["achievements"]["passes"]:
        passes += achievements + '\n'

    if certificates == '':
        certificates = '-'

    if passes == '':
        passes = '-'

    normalize_output = (f'<b>Обучающийся:🎒</b>\n'
                        f'\n{first_name} {last_name}\n'
                        f'\n<b>Дипломы:🧑‍🎓</b>\n'
                        f'{certificates}\n'
                        f'\n<b>Зачёты:✅</b>\n'
                        f'{passes}\n'
                        f'\n<b>Посещаемые курсы:👩‍💻👩‍🏫</b>\n'
                        )
    for course in courses:
        normalize_output += f'{course}'

    return normalize_output
