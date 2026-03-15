from aiogram.fsm.state import State, StatesGroup

class AntiSpamSettings(StatesGroup):
    edit_mps = State()
    edit_cpm = State()
    edit_words = State()
    edit_block_minutes = State()
    manual_block_user = State()
    manual_block_reason = State()
    manual_unblock_user = State()