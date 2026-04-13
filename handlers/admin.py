from maxo import Router
from maxo.fsm import FSMContext, State, StateFilter, StatesGroup
from maxo.fsm.state import default_state
from maxo.integrations.magic_filter import MagicFilter
from maxo.routing.ctx import Ctx
from maxo.routing.filters import Command
from maxo.routing.updates import MessageCallback, MessageCreated
from maxo.types.photo_attachment_request import PhotoAttachmentRequest
from maxo.types.video_attachment_request import VideoAttachmentRequest
from maxo.utils.facades import MessageCallbackFacade, MessageCreatedFacade
from magic_filter import F

from keyboards.inlinekeyboards import create_inline_keyboards_callback
from keyboards.keyboards import create_keyboards
from lexicon.lexicon import ADMIN_BUTTON_LEXICON
from utils import IsAdmin

# Роутер для админского функционала.
admin_router = Router(name="user")

# Начальный список админов (дальше дополняется данными из Redis).
admin_list = [230233015]
# Глобальный фильтр: этот роутер обрабатывает сообщения только администраторов.
admin_router.message.filter(IsAdmin(admin_list=admin_list, redis_set="admins"))


class FSMAdmin(StatesGroup):
    # Пользователь находится в панели администратора.
    admin_panel = State()
    # Шаг добавления видео.
    add_video = State()
    # Шаг добавления фото.
    add_photo = State()
    # Шаг добавления нового администратора.
    add_new_admin = State()
    # Шаг удаления администратора.
    delete_admin = State()
    # Зарезервированные состояния для удаления медиа.
    delete_photo = State()
    delete_video = State()


# Возврат в админ-панель из любого промежуточного состояния по кнопкам "отмена"/"ок".
@admin_router.message(MagicFilter(F.text.in_(["отмена", "ок"])) & ~StateFilter(*[default_state, None]))
async def cancel_action(update: MessageCreated, facade: MessageCreatedFacade, state: FSMContext):
    button_list = [value for _, value in ADMIN_BUTTON_LEXICON.items()]  # Формируем набор кнопок панели.
    keyboard = create_keyboards(*button_list)
    await facade.answer_text(
        text="Панель Администратора",
        keyboard=keyboard,
    )
    await state.set_state(FSMAdmin.admin_panel)  # Принудительно возвращаем в базовое админ-состояние.


# /admin — вход в панель администратора из состояния None.
@admin_router.message(Command("admin") & StateFilter(None))
async def admin_panel(update: MessageCreated, facade: MessageCreatedFacade, state: FSMContext):
    button_list = [value for _, value in ADMIN_BUTTON_LEXICON.items()]
    keyboard = create_keyboards(*button_list)
    await facade.answer_text(
        text="Панель Администратора",
        keyboard=keyboard,
    )
    await state.set_state(FSMAdmin.admin_panel)


# Выход из админ-панели.
@admin_router.message(MagicFilter(F.text == ADMIN_BUTTON_LEXICON["quit"]) & StateFilter(FSMAdmin.admin_panel))
async def disable_admin_panel(update: MessageCreated, facade: MessageCreatedFacade, state: FSMContext):
    await facade.answer_text(
        text="Вы вышли из панели администратора.\n"
        "Что бы вернуться в админ-режим введите команду /admin "
    )
    await state.clear()  # Полностью очищаем FSM-состояние.


# Запрос на добавление нового администратора.
@admin_router.message(MagicFilter(F.text == ADMIN_BUTTON_LEXICON["add_new_admin"]) & StateFilter(FSMAdmin.admin_panel))
async def add_new_admin(update: MessageCreated, facade: MessageCreatedFacade, state: FSMContext):
    await facade.answer_text(
        text="Перешлите мне любое сообщения от пользователя "
        "которому хотите выдать админ-права",
        keyboard=create_keyboards("отмена"),
    )
    await state.set_state(FSMAdmin.add_new_admin)


# Сохранение нового администратора по пересланному сообщению.
@admin_router.message(MagicFilter(F.text != "отмена") & StateFilter(FSMAdmin.add_new_admin))
async def save_new_admin(update: MessageCreated, facade: MessageCreatedFacade, state: FSMContext, ctx: Ctx):
    redis_client = ctx.get("redis_client")
    button_list = [value for _, value in ADMIN_BUTTON_LEXICON.items()]
    keyboard = create_keyboards(*button_list)

    # В maxo данные о пересланном сообщении лежат в update.message.link.
    if update.message.link:
        user = update.message.link.sender
        await redis_client.sadd("admins", user.user_id)  # Добавляем id пользователя в set админов.
        await redis_client.hmset("admin_names", {f"{user.user_id}": user.first_name})  # Сохраняем имя для интерфейса.

        await facade.answer_text("Новый Администратор успешно добавлен!")
        await state.set_state(FSMAdmin.admin_panel)
        await facade.answer_text(
            text="Панель администратора:",
            keyboard=keyboard,
        )
    else:
        await facade.answer_text(
            text="на данном шаге нужно переслать любое сообщение от пользователя "
            "которого хотите назначить администратором",
            keyboard=create_keyboards("отмена"),
        )


# Переход к шагу удаления администратора.
@admin_router.message(MagicFilter(F.text == ADMIN_BUTTON_LEXICON["delete_admin"]) & StateFilter(FSMAdmin.admin_panel))
async def response_delete_admin(update: MessageCreated, facade: MessageCreatedFacade, state: FSMContext, ctx: Ctx):
    redis_client = ctx.get("redis_client")
    admin_dict = await redis_client.hgetall("admin_names")  # Получаем пары {admin_id: имя}.

    if admin_dict:
        await facade.answer_text(
            text="Выберите админа которого хотите удалить:",
            keyboard=create_inline_keyboards_callback(admin_dict),  # payload кнопки = admin_id.
        )
        await state.set_state(FSMAdmin.delete_admin)
    else:
        await facade.answer_text(
            text="Список админов пуст",
            keyboard=create_keyboards("ок"),
        )


# Удаление администратора по callback payload.
@admin_router.callback_query(MagicFilter(F.payload) & StateFilter(FSMAdmin.delete_admin))
async def delete_admin(update: MessageCallback, facade: MessageCallbackFacade, state: FSMContext, ctx: Ctx):
    redis_client = ctx.get("redis_client")
    admin_dict = await redis_client.hgetall("admin_names")
    admin_id = update.payload

    # Валидация: в payload ожидается числовой id пользователя.
    if not admin_id.isdigit():
        await facade.callback_answer("Выберите администратора которого хотите удалить из списка выше")
        return

    is_admin = await redis_client.sismember("admins", admin_id)
    if not is_admin:
        await facade.callback_answer("Выберите администратора которого хотите удалить из списка выше")
        return

    await redis_client.srem("admins", admin_id)  # Удаляем из множества админов.
    await redis_client.hdel("admin_names", admin_id)  # Удаляем имя из hash.

    await facade.answer_text(
        f"{admin_dict[admin_id]} Больше не является Администратором",
        keyboard=create_keyboards("ок"),
    )
    await state.set_state(FSMAdmin.admin_panel)


# Переход к шагу добавления фото.
@admin_router.message(MagicFilter(F.text == ADMIN_BUTTON_LEXICON["add_photo"]) & StateFilter(FSMAdmin.admin_panel))
async def start_add_photo(update: MessageCreated, facade: MessageCreatedFacade, state: FSMContext):
    await facade.answer_text(
        text="Пришлите, пожалуйста, фотографии, которые планируете добавить",
        keyboard=create_keyboards("отмена"),
    )
    await state.set_state(FSMAdmin.add_photo)


# Сохранение токенов фото в Redis.
# ВАЖНО: сохраняем token (а не photo_id), потому что для повторной отправки через send_media нужен именно token.
@admin_router.message(StateFilter(FSMAdmin.add_photo))
async def save_photo(update: MessageCreated, facade: MessageCreatedFacade, state: FSMContext, ctx: Ctx):
    redis_client = ctx.get("redis_client")
    photos = update.message.body.photo
    if not photos:
        await facade.answer_text("Не вижу фото в сообщении, пришлите изображение")
        return

    photo_list = await redis_client.lrange("photos", 0, -1)
    video_list = await redis_client.lrange("videos", 0, -1)

    free_slots = 10 - len(photo_list+video_list)  # Ограничиваем хранилище 10 элементами.
    if free_slots <= 0:
        await facade.answer_text(
            "Количество медиа - файлов в хранилище достигло 10 шт,"
            "Сначала удалите не нужные"
        )
    else:
        saved_count = 0
        for photo in photos[:free_slots]:
            await redis_client.rpush("photos", str(photo.payload.token))
            saved_count += 1

        if saved_count == len(photos):
            message_text = f"Сохранено фотографий: {saved_count}"
        else:
            message_text = (
                f"Сохранено фотографий: {saved_count}. "
                f"Остальные не сохранены: достигнут лимит 10 шт."
            )

        await facade.answer_text(message_text, keyboard=create_keyboards("ок"))

    await state.set_state(FSMAdmin.admin_panel)


# Переход к шагу добавления видео.
@admin_router.message(MagicFilter(F.text == ADMIN_BUTTON_LEXICON["add_video"]) & StateFilter(FSMAdmin.admin_panel))
async def start_add_video(update: MessageCreated, facade: MessageCreatedFacade, state: FSMContext):
    await facade.answer_text(
        text="Пришлите, пожалуйста, видеоматериалы, которые планируете добавить",
        keyboard=create_keyboards("отмена"),
    )
    await state.set_state(FSMAdmin.add_video)


# Сохранение токенов видео в Redis.
# Здесь такой же подход: для повторной отправки через API удобнее хранить token.
@admin_router.message(StateFilter(FSMAdmin.add_video))
async def save_video(update: MessageCreated, facade: MessageCreatedFacade, state: FSMContext, ctx: Ctx):
    redis_client = ctx.get("redis_client")
    videos = update.message.body.video
    if not videos:
        await facade.answer_text("Не вижу видео в сообщении, пришлите видео.")
        return

    video_list = await redis_client.lrange("videos", 0, -1)
    photo_list = await redis_client.lrange("photos", 0, -1)
    free_slots = 10 - len(video_list+photo_list)
    if free_slots <= 0:
        await facade.answer_text(
            "Количество медиа - файлов в хранилище достигло 10 шт,"
            "Сначала удалите не нужные."
        )
    else:
        saved_count = 0
        for video in videos[:free_slots]:
            await redis_client.rpush("videos", str(video.payload.token))
            saved_count += 1

        if saved_count == len(videos):
            message_text = f"Сохранено видеоматериалов: {saved_count}"
        else:
            message_text = (
                f"Сохранено видеоматериалов: {saved_count}. "
                f"Остальные не сохранены: достигнут лимит 10 шт."
            )

        await facade.answer_text(message_text, keyboard=create_keyboards("ок"))

    await state.set_state(FSMAdmin.admin_panel)


# Просмотр всех фотографий из Redis одним сообщением (media group).
@admin_router.message(MagicFilter(F.text == ADMIN_BUTTON_LEXICON["get_photos"]) & StateFilter(FSMAdmin.admin_panel))
async def get_photos(update: MessageCreated, facade: MessageCreatedFacade, state: FSMContext, ctx: Ctx):
    redis_client = ctx.get("redis_client")
    photo_list = await redis_client.lrange("photos", 0, -1)

    if not photo_list:
        await facade.answer_text(
            "фотографий пока нет.",
            keyboard=create_keyboards("ок"),
        )
        return

    media = []
    for token in photo_list:
        # Redis может вернуть bytes, а фабрика ожидает строковый token.
        if isinstance(token, bytes):
            token = token.decode()
        media.append(PhotoAttachmentRequest.factory(token=str(token)))

    await facade.send_media(media,keyboard=create_keyboards('ок'))  # send_media умеет отправлять список медиа одним сообщением.

# Просмотр всех видео из Redis одним сообщением (media group).
@admin_router.message(MagicFilter(F.text == ADMIN_BUTTON_LEXICON["get_videos"]) & StateFilter(FSMAdmin.admin_panel))
async def get_photos(update: MessageCreated, facade: MessageCreatedFacade, state: FSMContext, ctx: Ctx):
    redis_client = ctx.get("redis_client")
    video_list = await redis_client.lrange("videos", 0, -1)

    if not video_list:
        await facade.answer_text(
            "Видеоматериалов пока нет.",
            keyboard=create_keyboards("ок"),
        )
        return

    media = []
    for token in video_list:
        # Redis может вернуть bytes, а фабрика ожидает строковый token.
        if isinstance(token, bytes):
            token = token.decode()
        media.append(VideoAttachmentRequest.factory(token=str(token)))

    await facade.send_media(media,keyboard=create_keyboards('ок'))  # send_media умеет отправлять список медиа одним сообщением.


# запрос на удаление видео
@admin_router.message(MagicFilter(F.text == ADMIN_BUTTON_LEXICON['delete_video']) & StateFilter(FSMAdmin.admin_panel))
async def request_for_remove_video(update:MessageCreated,facade:MessageCreatedFacade, state:FSMContext,ctx: Ctx):
    redis_client = ctx.get("redis_client")
    video_list = await redis_client.lrange("videos", 0, -1)
    if not video_list:
        await facade.answer_text(
            text='видеоматериалов нет, удалять нечего',
            keyboard=create_keyboards('отмена')
        )
        return
    else:
        await facade.answer_text(
            text='Введите порядковый номер видео которое хотите удалить',
            keyboard=create_keyboards('отмена')
        )
        await state.set_state(FSMAdmin.delete_video)

# удаление видео
@admin_router.message(MagicFilter(F.text !='отмена') & StateFilter(FSMAdmin.delete_video))
async def delete_video(update:MessageCreated,facade:MessageCreatedFacade, state:FSMContext, ctx: Ctx):
    if update.text.isdigit() and ( 0< int(update.text) <=10 ):
        redis_client = ctx.get("redis_client")
        delete_video_id = await redis_client.lindex("videos", int(update.text)-1)
        if delete_video_id:
            await redis_client.lrem('videos',1,delete_video_id)
            await facade.answer_text('Вы удалили данное видео:')
            await facade.send_media(
                VideoAttachmentRequest.factory(token=str(delete_video_id)),
                keyboard=create_keyboards('ок')
            )
        else:
            await facade.answer_text(
                text='Видео под таким индексом нет',
                keyboard=create_keyboards('отмена')
            )


# запрос на удаление фото
@admin_router.message(MagicFilter(F.text == ADMIN_BUTTON_LEXICON['delete_photo']) & StateFilter(FSMAdmin.admin_panel))
async def request_for_remove_video(update: MessageCreated, facade: MessageCreatedFacade, state: FSMContext, ctx: Ctx):
    redis_client = ctx.get("redis_client")
    photo_list = await redis_client.lrange("photos", 0, -1)
    if not photo_list:
        await facade.answer_text(
            text='фотографий нет, удалять нечего.',
            keyboard=create_keyboards('отмена')
        )
        return
    else:
        await facade.answer_text(
            text='Введите порядковый номер фото которое хотите удалить',
            keyboard=create_keyboards('отмена')
        )
        await state.set_state(FSMAdmin.delete_photo)


# удаление фото
@admin_router.message(MagicFilter(F.text != 'отмена') & StateFilter(FSMAdmin.delete_photo))
async def delete_video(update: MessageCreated, facade: MessageCreatedFacade, state: FSMContext, ctx: Ctx):
    if update.text.isdigit() and (0 < int(update.text) <= 10):
        redis_client = ctx.get("redis_client")
        delete_photo_id = await redis_client.lindex("photos", int(update.text) - 1)
        if delete_photo_id:
            await redis_client.lrem('photos', 1, delete_photo_id)
            await facade.answer_text('Вы удалили данное фото:')
            await facade.send_media(
                PhotoAttachmentRequest.factory(token=str(delete_photo_id)),
                keyboard=create_keyboards('ок')
            )

        else:
            await facade.answer_text(
                text='фотографии под таким индексом нет',
                keyboard=create_keyboards('отмена')
            )
