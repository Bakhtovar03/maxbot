
from maxo.utils.builders import KeyboardBuilder


from lexicon.lexicon import BUTTON_LEXICON


def create_inline_keyboards(*buttons: str):
    builder = KeyboardBuilder()
    for button in buttons:
        builder.add_callback(
            text=BUTTON_LEXICON.get(button,button),
            payload=str(button)
        ).adjust(1)
    return builder.build()

def create_inline_keyboards_callback(buttons:dict[int,str]):
    builder = KeyboardBuilder()
    for admin_id,name in buttons.items():
        builder.add_callback(
            text=name,
            payload=str(admin_id)
        ).adjust(1)
    return builder.build()