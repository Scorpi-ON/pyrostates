import asyncio
import aiosqlite
from typing import Self
from pathlib import Path

from pyrogram import filters, types
from pyrogram.types import Message, CallbackQuery, Chat, User


class State:
    def __init__(self, name: str, data: str | None = None) -> None:
        self.name = name
        self.data = data


ObjectContainingUserId = types.Update | str | int
StateOrStateName = State | str


class StateMachine:
    @staticmethod
    def _get_user_id(object_containing_user_id: ObjectContainingUserId) -> int:
        if isinstance(object_containing_user_id, Message):
            if object_containing_user_id.from_user:
                return object_containing_user_id.from_user.id
            if object_containing_user_id.sender_chat:
                return object_containing_user_id.sender_chat.id
            raise NotImplementedError(...)
        if isinstance(object_containing_user_id, CallbackQuery):
            return object_containing_user_id.from_user.id
        if isinstance(object_containing_user_id, Chat | User):
            return object_containing_user_id.id
        if isinstance(object_containing_user_id, str):
            return int(object_containing_user_id)
        if isinstance(object_containing_user_id, int):
            return object_containing_user_id
        raise NotImplementedError(...)

    @staticmethod
    def _unpack_state(state: StateOrStateName) -> tuple[str, str | None]:
        if isinstance(state, State):
            return state.name, state.data
        return state, None

    async def init_db(self, database: str | Path = ':memory:') -> Self:
        query = '''
        CREATE TABLE IF NOT EXISTS pyrogram_user_states(
            user_id INTEGER PRIMARY KEY,
            state TEXT NOT NULL,
            state_data TEXT
        );
        '''
        self._db = await aiosqlite.connect(database, check_same_thread=False)
        await self._db.execute(query)
        await self._db.commit()

    def __init__(self, database: str | Path = ':memory:') -> None:
        self._db: aiosqlite.Connection
        asyncio.run(self.init_db(database))

    async def _insert_user_state(
            self, 
            user_id: int, 
            state: State,
    ) -> None:
        query = '''INSERT INTO pyrogram_user_states VALUES (?, ?, ?);'''
        await self._db.execute(query, (user_id, state.name, state.data))
        await self._db.commit()

    async def _update_user_state(self, user_id: int, state: State) -> None:
        query = '''
        UPDATE pyrogram_user_states 
        SET state = ?, state_data = ? 
        WHERE user_id = ?;
        '''
        await self._db.execute(query, (user_id, state.name, state.data))
        await self._db.commit()

    async def _delete_user_state(self, user_id: int) -> None:
        query = '''DELETE FROM pyrogram_user_states WHERE user_id = ?;'''
        await self._db.execute(query, (user_id))
        await self._db.commit()

    async def _select_user_state(self, user_id: int) -> State | None:
        query = '''SELECT state, data FROM pyrogram_user_states WHERE user_id = ?;'''
        async with self._db.execute(query, (user_id,)) as cursor:
            result = await cursor.fetchone()
            if result is None:
                return None
            state, data = result
            return State(state, data)

    async def __getitem__(
            self, 
            object_containing_user_id: ObjectContainingUserId
    ) -> State | None:
        user_id = self._get_user_id(object_containing_user_id)
        return await self._select_user_state(user_id)

    async def __setitem__(
            self, 
            object_containing_user_id: ObjectContainingUserId, 
            state_or_state_name: StateOrStateName
    ) -> None:
        user_id = self._get_user_id(object_containing_user_id)
        name, data = self._unpack_state(state_or_state_name)
        state = State(name, data)
        if self[user_id] is None:
            await self._insert_user_state(user_id, state)
        else:
            await self._update_user_state(user_id, state)

    async def __delitem__(
            self,
            object_containing_user_id: ObjectContainingUserId
    ) -> None:
        user_id = self._get_user_id(object_containing_user_id)
        if self[user_id] is None:
            err_msg = 'User does not exist'
            raise KeyError(err_msg)
        await self._delete_user_state(user_id)

    def at(self, state: StateOrStateName) -> filters.Filter:
        @filters.create
        async def at_state(_, __, update: types.Update) -> bool:
            current_state = await self[update]
            if current_state is None:
                return False
            state_name, _ = self._unpack_state(state)
            return current_state.name == state_name
        return at_state
