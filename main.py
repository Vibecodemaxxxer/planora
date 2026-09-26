"""
main.py

Точка входа приложения Planora. Здесь происходит только запуск:
создаётся объект приложения Qt, подключается оформление, открывается
база данных и показывается главное окно. Вся логика вынесена в отдельные
модули, чтобы этот файл оставался коротким и понятным.

Запуск: python main.py
"""

import os
import sys

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication

from constants import APP_NAME, STYLE_PATH
from database import Database
from main_window import MainWindow


def load_stylesheet(path: str) -> str:
    """Читает файл оформления QSS.

    QSS — это "CSS для Qt": текстовый файл с правилами внешнего вида
    виджетов. Файла может ещё не быть (стиль пишем на Дне 3), поэтому
    отсутствие файла не считаем ошибкой — приложение просто запустится
    со стандартным видом.
    """
    if not os.path.exists(path):
        return ""
    with open(path, encoding="utf-8") as style_file:
        return style_file.read()


def main() -> None:
    """Собирает приложение и запускает цикл обработки событий."""
    # Убираем кнопку "?" в заголовке диалоговых окон. Qt добавляет её на
    # Windows по умолчанию: это старый механизм подсказок "Что это?", а
    # подсказки у нас обычные, всплывающие при наведении. Атрибут нужно
    # задать до создания QApplication — он влияет на то, как создаются окна.
    QApplication.setAttribute(Qt.AA_DisableWindowContextHelpButton, True)

    # QApplication — обязательный объект любого Qt-приложения: он
    # обрабатывает события (клики, нажатия клавиш, перерисовку) и должен
    # быть создан раньше любых виджетов.
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)

    # Стиль задаётся приложению целиком, поэтому правила действуют сразу
    # во всех окнах и диалогах.
    app.setStyleSheet(load_stylesheet(STYLE_PATH))

    # База создаётся здесь и передаётся окну — при первом запуске
    # Database сам создаст файл planora.db, таблицы и категории
    # по умолчанию.
    database = Database()

    window = MainWindow(database)
    window.show()

    # app.exec_() запускает цикл обработки событий и не возвращает
    # управление, пока пользователь не закроет приложение. Именно
    # поэтому закрытие базы стоит после этой строки.
    exit_code = app.exec_()

    database.close()
    sys.exit(exit_code)


# Проверка нужна, чтобы код запуска выполнялся только при прямом вызове
# файла (python main.py), но не при импорте модуля.
if __name__ == "__main__":
    main()
