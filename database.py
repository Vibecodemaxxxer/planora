"""
database.py

Класс Database инкапсулирует всю работу с SQLite: создание таблиц и
CRUD-операции (создание/чтение/изменение/удаление) для категорий, задач
и подзадач. Остальной код приложения (окна, диалоги) работает с базой
только через методы этого класса и никогда не пишет SQL напрямую — так
UI-код не зависит от деталей хранения данных, и его проще менять и
тестировать.
"""

import sqlite3
from datetime import date
from typing import Any, List, Optional, Tuple

from constants import DB_PATH, DEFAULT_CATEGORIES


class Database:
    """Обёртка над sqlite3 для работы с базой данных Planora."""

    def __init__(self, db_path: str = DB_PATH) -> None:
        # check_same_thread=False — небольшой запас прочности на случай,
        # если обращение к БД когда-нибудь понадобится не строго из
        # главного потока Qt.
        self._connection = sqlite3.connect(db_path, check_same_thread=False)

        # sqlite3.Row позволяет обращаться к полям результата по имени
        # (row["title"]), а не только по числовому индексу — это делает
        # остальной код читаемее.
        self._connection.row_factory = sqlite3.Row

        # SQLite по умолчанию НЕ проверяет внешние ключи, их нужно
        # включать отдельно для каждого соединения.
        self._connection.execute("PRAGMA foreign_keys = ON")

        self._create_tables()
        self._seed_default_categories()

    # ------------------------------------------------------------------
    # Инициализация схемы
    # ------------------------------------------------------------------
    def _create_tables(self) -> None:
        """Создаёт таблицы categories, tasks, subtasks, если их ещё нет."""
        cursor = self._connection.cursor()

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS categories (
                id    INTEGER PRIMARY KEY AUTOINCREMENT,
                name  TEXT NOT NULL UNIQUE,
                color TEXT NOT NULL
            )
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                title       TEXT NOT NULL,
                description TEXT,
                deadline    TEXT,
                priority    TEXT NOT NULL,
                category_id INTEGER,
                is_done     INTEGER NOT NULL DEFAULT 0,
                image_path  TEXT,
                created_at  TEXT NOT NULL,
                FOREIGN KEY (category_id) REFERENCES categories (id)
                    ON DELETE SET NULL
            )
            """
        )

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS subtasks (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id  INTEGER NOT NULL,
                text     TEXT NOT NULL,
                is_done  INTEGER NOT NULL DEFAULT 0,
                position INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY (task_id) REFERENCES tasks (id)
                    ON DELETE CASCADE
            )
            """
        )

        self._connection.commit()

    def _seed_default_categories(self) -> None:
        """При самом первом запуске (когда таблица categories пуста)
        создаёт набор категорий по умолчанию из constants.py."""
        if self.get_categories():
            return  # категории уже есть — ничего не делаем
        for name, color in DEFAULT_CATEGORIES:
            self.add_category(name, color)

    # ------------------------------------------------------------------
    # Категории
    # ------------------------------------------------------------------
    def get_categories(self) -> List[sqlite3.Row]:
        cursor = self._connection.execute(
            "SELECT id, name, color FROM categories ORDER BY name"
        )
        return cursor.fetchall()

    def add_category(self, name: str, color: str) -> int:
        cursor = self._connection.execute(
            "INSERT INTO categories (name, color) VALUES (?, ?)",
            (name, color),
        )
        self._connection.commit()
        return cursor.lastrowid

    def rename_category(self, category_id: int, new_name: str) -> None:
        self._connection.execute(
            "UPDATE categories SET name = ? WHERE id = ?",
            (new_name, category_id),
        )
        self._connection.commit()

    def set_category_color(self, category_id: int, color: str) -> None:
        self._connection.execute(
            "UPDATE categories SET color = ? WHERE id = ?",
            (color, category_id),
        )
        self._connection.commit()

    def category_has_tasks(self, category_id: int) -> bool:
        """True, если у категории есть хотя бы одна задача.
        Используется перед удалением категории — по ТЗ категорию
        с задачами удалять нельзя, приложение должно предупредить."""
        cursor = self._connection.execute(
            "SELECT COUNT(*) FROM tasks WHERE category_id = ?",
            (category_id,),
        )
        count = cursor.fetchone()[0]
        return count > 0

    def delete_category(self, category_id: int) -> None:
        self._connection.execute(
            "DELETE FROM categories WHERE id = ?", (category_id,)
        )
        self._connection.commit()

    # ------------------------------------------------------------------
    # Задачи
    # ------------------------------------------------------------------
    def add_task(
        self,
        title: str,
        description: Optional[str],
        deadline: Optional[str],
        priority: str,
        category_id: Optional[int],
        image_path: Optional[str] = None,
    ) -> int:
        """Создаёт задачу и возвращает её id.
        deadline ожидается строкой в формате constants.DATE_FORMAT_DB
        (например, "2026-09-30") или None, если срок не задан."""
        cursor = self._connection.execute(
            """
            INSERT INTO tasks
                (title, description, deadline, priority, category_id,
                 is_done, image_path, created_at)
            VALUES (?, ?, ?, ?, ?, 0, ?, ?)
            """,
            (
                title,
                description,
                deadline,
                priority,
                category_id,
                image_path,
                date.today().isoformat(),
            ),
        )
        self._connection.commit()
        return cursor.lastrowid

    def update_task(self, task_id: int, **fields: Any) -> None:
        """Обновляет только переданные поля задачи, остальные не трогает.

        Пример:
            db.update_task(5, title="Новое название", priority="Высокий")

        Имена полей всегда приходят из нашего же кода (не от пользователя
        напрямую), поэтому подстановка имён столбцов через f-строку здесь
        безопасна — через "?" в SQL можно параметризовать только значения,
        но не имена столбцов.
        """
        if not fields:
            return
        columns = ", ".join(f"{key} = ?" for key in fields)
        values = list(fields.values()) + [task_id]
        self._connection.execute(
            f"UPDATE tasks SET {columns} WHERE id = ?", values
        )
        self._connection.commit()

    def set_task_done(self, task_id: int, is_done: bool) -> None:
        self.update_task(task_id, is_done=int(is_done))

    def delete_task(self, task_id: int) -> None:
        # Подзадачи этой задачи удалятся автоматически благодаря
        # ON DELETE CASCADE в схеме таблицы subtasks.
        self._connection.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        self._connection.commit()

    def get_tasks(self) -> List[sqlite3.Row]:
        """Все задачи. Задачи без срока (deadline IS NULL) — в конце."""
        cursor = self._connection.execute(
            "SELECT * FROM tasks ORDER BY deadline IS NULL, deadline"
        )
        return cursor.fetchall()

    def get_task(self, task_id: int) -> Optional[sqlite3.Row]:
        cursor = self._connection.execute(
            "SELECT * FROM tasks WHERE id = ?", (task_id,)
        )
        return cursor.fetchone()

    def get_tasks_by_date(self, iso_date: str) -> List[sqlite3.Row]:
        """Задачи с дедлайном ровно на указанную дату — для режима
        "Календарь" (клик по дню)."""
        cursor = self._connection.execute(
            "SELECT * FROM tasks WHERE deadline = ? ORDER BY priority",
            (iso_date,),
        )
        return cursor.fetchall()

    # ------------------------------------------------------------------
    # Подзадачи
    # ------------------------------------------------------------------
    def add_subtask(self, task_id: int, text: str) -> int:
        position = self._next_subtask_position(task_id)
        cursor = self._connection.execute(
            """
            INSERT INTO subtasks (task_id, text, is_done, position)
            VALUES (?, ?, 0, ?)
            """,
            (task_id, text, position),
        )
        self._connection.commit()
        return cursor.lastrowid

    def _next_subtask_position(self, task_id: int) -> int:
        """Следующий порядковый номер для нового пункта подзадач этой
        задачи (чтобы пункты не перемешивались в списке)."""
        cursor = self._connection.execute(
            """
            SELECT COALESCE(MAX(position), -1) + 1
            FROM subtasks WHERE task_id = ?
            """,
            (task_id,),
        )
        return cursor.fetchone()[0]

    def get_subtasks(self, task_id: int) -> List[sqlite3.Row]:
        cursor = self._connection.execute(
            "SELECT * FROM subtasks WHERE task_id = ? ORDER BY position",
            (task_id,),
        )
        return cursor.fetchall()

    def count_subtasks(self, task_id: int) -> Tuple[int, int]:
        """Возвращает пару (выполнено, всего) подзадач задачи.

        Нужна для полоски прогресса на карточке ("2 из 5"). Считаем
        одним SQL-запросом, а не загрузкой всех подзадач в Python:
        карточек в списке много, и каждая лишняя строка из БД — лишняя
        работа. COALESCE подставляет 0 вместо NULL, который SUM
        возвращает, когда подзадач нет вообще.
        """
        cursor = self._connection.execute(
            """
            SELECT COALESCE(SUM(is_done), 0), COUNT(*)
            FROM subtasks WHERE task_id = ?
            """,
            (task_id,),
        )
        done, total = cursor.fetchone()
        return done, total

    def set_subtask_done(self, subtask_id: int, is_done: bool) -> None:
        self._connection.execute(
            "UPDATE subtasks SET is_done = ? WHERE id = ?",
            (int(is_done), subtask_id),
        )
        self._connection.commit()

    def delete_subtask(self, subtask_id: int) -> None:
        self._connection.execute(
            "DELETE FROM subtasks WHERE id = ?", (subtask_id,)
        )
        self._connection.commit()

    # ------------------------------------------------------------------
    def close(self) -> None:
        self._connection.close()
