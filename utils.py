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


