"""
dialogs.py

Две обёртки над QMessageBox — предупреждение и вопрос «да / нет».

Зачем понадобился отдельный файл. Готовые вызовы вида
QMessageBox.question(...) удобны, но у них нельзя поменять надписи на
кнопках: Qt подставляет свои, английские ("Yes", "No", "OK"). Чтобы
кнопки были русскими, окно приходится собирать вручную — создавать
QMessageBox, добавлять кнопки со своим текстом и запускать.

Такие окна нужны в трёх файлах (главное окно, окно задачи, окно
категорий). Складывать один и тот же десяток строк в каждый из них —
значит трижды поддерживать одно и то же, поэтому они вынесены сюда.
"""

from PyQt5.QtWidgets import QMessageBox

from constants import BUTTON_NO, BUTTON_OK, BUTTON_YES


def show_warning(parent, header: str, text: str) -> None:
    """Показывает предупреждение с кнопкой «ОК».

    parent — окно, поверх которого появится сообщение. Оно же не даёт
    пользователю работать с родительским окном, пока не ответит.
    """
    message_box = QMessageBox(parent)
    message_box.setIcon(QMessageBox.Warning)
    message_box.setWindowTitle(header)
    message_box.setText(text)

    # addButton возвращает созданную кнопку; роль говорит Qt, чем эта
    # кнопка является по смыслу — от этого зависит, например, что
    # сработает по нажатию Esc.
    message_box.addButton(BUTTON_OK, QMessageBox.AcceptRole)

    message_box.exec_()


def ask_yes_no(parent, header: str, text: str) -> bool:
    """Задаёт вопрос с кнопками «Да» и «Нет». True — выбрали «Да»."""
    message_box = QMessageBox(parent)
    message_box.setIcon(QMessageBox.Question)
    message_box.setWindowTitle(header)
    message_box.setText(text)

    yes_button = message_box.addButton(BUTTON_YES, QMessageBox.YesRole)
    no_button = message_box.addButton(BUTTON_NO, QMessageBox.NoRole)

    # Кнопка по умолчанию — «Нет»: эти вопросы у нас про удаление,
    # и случайное нажатие Enter не должно ничего стирать.
    message_box.setDefaultButton(no_button)

    message_box.exec_()

    # clickedButton() возвращает ту кнопку, которую нажали. Сравниваем
    # с нашей: если окно закрыли крестиком, она будет другой (или None),
    # и ответ будет считаться отрицательным.
    return message_box.clickedButton() is yes_button
