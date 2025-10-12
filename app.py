import streamlit as st
import gspread
import pandas as pd
import re
from datetime import datetime, timedelta
import urllib.parse
import time
from typing import List, Dict, Any
import math 
from io import StringIO


# =========================================================
# 1. КОНСТАНТЫ И НАСТРОЙКИ
# =========================================================


# Настройки Google Sheets
SPREADSHEET_NAME = "Start" 
WORKSHEET_NAME_ORDERS = "ЗАЯВКИ"
WORKSHEET_NAME_PRICE = "ПРАЙС"


# Заголовки, которые должны быть на листе 'ЗАЯВКИ'
EXPECTED_HEADERS = [
    "ДАТА_ВВОДА", "НОМЕР_ЗАЯВКИ", "ТЕЛЕФОН", "АДРЕС", "ДАТА_ДОСТАВКИ", 
    "КОММЕНТАРИЙ", "ЗАКАЗ", "СУММА"
]


# УКАЖИТЕ СВОЙ НОМЕР МЕНЕДЖЕРА 
MANAGER_WHATSAPP_PHONE = "79000000000" 




st.set_page_config(
    page_title="CRM: Ввод Новой Заявки", 
    layout="wide",
    initial_sidebar_state="expanded"
)


# --- Вспомогательные функции ---
def set_critical_error(message, error_details=None):
    """Функция для записи критической ошибки и остановки приложения."""
    full_message = f"Критическая ошибка: {message}"
    if error_details:
        full_message += f"\n\nДетали: {error_details}"
    st.session_state.critical_error = full_message
    
def get_default_delivery_date():
    return datetime.today().date() + timedelta(days=1)


def clear_form_state():
    """Сброс всех полей после успешной отправки."""
    st.session_state.calculator_items = []
    
    # Удаляем ключи, привязанные к input-виджетам, чтобы сбросить их
    for key in ['k_client_phone', 'k_address', 'k_comment']:
        if key in st.session_state:
            del st.session_state[key]
            
    # При сбросе формы перегенерируем номер заявки
    st.session_state['k_order_number'] = load_last_order_number()
    
    # Сброс остальных полей
    st.session_state.conversation_text_input = ""
    st.session_state.k_delivery_date = get_default_delivery_date()
    
def is_valid_phone(phone: str) -> bool:
    """Проверяет, соответствует ли телефон формату 7XXXXXXXXXX."""
    normalized = re.sub(r'\D', '', phone)
    return len(normalized) == 11 and normalized.startswith('7')


# =========================================================
# 2. ФУНКЦИИ ПОДКЛЮЧЕНИЯ И КЭШИРОВАНИЯ
# =========================================================


@st.cache_resource(ttl=3600)
def get_gsheet_client():
    """Аутентификация и получение клиента gspread."""
    if "gcp_service_account" not in st.secrets:
        set_critical_error("Секрет 'gcp_service_account' не найден. Убедитесь, что он настроен в secrets.toml.")
        return None 
    try:
        gc = gspread.service_account_from_dict(st.secrets["gcp_service_account"])
        return gc
    except Exception as e:
        set_critical_error("Ошибка аутентификации gspread.", f"Ошибка: {e}")
        return None


def initialize_worksheet_headers(worksheet: gspread.Worksheet):
    """Проверяет и записывает заголовки на лист 'ЗАЯВКИ'."""
    try:
        current_headers = worksheet.row_values(1)
        
        if current_headers == EXPECTED_HEADERS:
            return


        if current_headers and len(current_headers) > 0 and current_headers != ['']:
             st.warning("⚠️ Заголовки листа 'ЗАЯВКИ' некорректны. Записываю новую структуру.")
             worksheet.update('A1', [EXPECTED_HEADERS])
        else:
             worksheet.insert_row(EXPECTED_HEADERS, 1)
             
        st.success("🎉 Структура листа 'ЗАЯВКИ' успешно инициализирована/обновлена.")


    except Exception as e:
        set_critical_error("Ошибка при инициализации заголовков листа 'ЗАЯВКИ'.", f"Ошибка: {e}")




@st.cache_data(ttl=5) 
def load_last_order_number() -> str:
    """Загружает последний номер заявки и возвращает следующий."""
    orders_ws = get_orders_worksheet()
    if not orders_ws:
        return "1001" 


    try:
        column_index = EXPECTED_HEADERS.index("НОМЕР_ЗАЯВКИ") + 1 
        column_values = orders_ws.col_values(column_index)
        
        if len(column_values) <= 1:
            return "1001" 
        
        order_numbers = [int(n) for n in column_values[1:] if n.isdigit()]
        
        if not order_numbers:
            return "1001"
            
        last_number = max(order_numbers)
        next_number = last_number + 1
        return str(next_number)
        
    except Exception as e:
        # Убрана ошибка, так как она уже может быть записана через set_critical_error в get_orders_worksheet
        # st.error(f"Не удалось получить последний номер заявки. Используется дефолтный 1001. Ошибка: {e}")
        return "1001"
        
@st.cache_data(ttl="1h")
def load_price_list():
    """Загрузка и кэширование прайс-листа из Google Sheets."""
    gc = get_gsheet_client()
    if not gc: return pd.DataFrame() 
        
    try:
        sh = gc.open(SPREADSHEET_NAME) 
        worksheet = sh.worksheet(WORKSHEET_NAME_PRICE) 
        data = worksheet.get_all_records()
        df = pd.DataFrame(data)
        
        if 'НАИМЕНОВАНИЕ' not in df.columns or 'ЦЕНА' not in df.columns:
            set_critical_error(
                f"В листе '{WORKSHEET_NAME_PRICE}' отсутствуют обязательные столбцы 'НАИМЕНОВАНИЕ' или 'ЦЕНА'."
            )
            return pd.DataFrame()
        
        df['ЦЕНА'] = pd.to_numeric(df['ЦЕНА'], errors='coerce') 
        df.dropna(subset=['ЦЕНА'], inplace=True)
        
        st.info(f"✅ Прайс-лист загружен успешно. Обнаружено {len(df)} позиций.")
        return df
    except gspread.exceptions.SpreadsheetNotFound:
        set_critical_error(f"Google Таблица '{SPREADSHEET_NAME}' не найдена.")
    except gspread.exceptions.WorksheetNotFound:
        set_critical_error(f"Лист '{WORKSHEET_NAME_PRICE}' не найден.")
    except Exception as e:
        set_critical_error("Неизвестная ошибка при загрузке прайса (проверьте заголовки и формат цены).", f"Ошибка: {e}")
    return pd.DataFrame()


@st.cache_resource
def get_orders_worksheet():
    """Получение и кэширование рабочего листа для заявок."""
    gc = get_gsheet_client()
    if not gc: return None
    try:
        sh = gc.open(SPREADSHEET_NAME) 
        worksheet = sh.worksheet(WORKSHEET_NAME_ORDERS)
        
        initialize_worksheet_headers(worksheet)
        
        return worksheet
    except gspread.exceptions.WorksheetNotFound:
        set_critical_error(f"Лист для заявок '{WORKSHEET_NAME_ORDERS}' не найден.")
        return None
    except Exception as e:
        set_critical_error(f"Ошибка доступа к листу '{WORKSHEET_NAME_ORDERS}'.", f"Ошибка: {e}")
        return None


# =========================================================
# 3. ФУНКЦИЯ ЗАГРУЗКИ ДАННЫХ ДЛЯ КОРРЕКТИРОВКИ
# =========================================================


def load_order_data(order_number: str):
    """
    Загружает данные заявки по номеру из Google Sheets и обновляет st.session_state.
    """
    orders_ws = get_orders_worksheet()
    if not orders_ws:
        st.error("Не удалось подключиться к базе данных.")
        return


    try:
        # Получаем все записи в виде списка словарей
        data = orders_ws.get_all_records()
        df = pd.DataFrame(data)
        
        # Фильтруем по номеру заявки
        # Ищем строгое совпадение, преобразуя все в строку
        target_row = df[df['НОМЕР_ЗАЯВКИ'].astype(str) == order_number]
        
        if target_row.empty:
            st.warning(f"⚠️ Заявка с номером **{order_number}** не найдена.")
            return


        # Найдена строка (берем первую, если есть дубликаты)
        row = target_row.iloc[0].to_dict()
        
        # 1. Обновляем основные поля формы
        st.session_state.k_order_number = str(row.get('НОМЕР_ЗАЯВКИ', ''))
        st.session_state.k_client_phone = str(row.get('ТЕЛЕФОН', ''))
        st.session_state.k_address = str(row.get('АДРЕС', ''))
        st.session_state.k_comment = str(row.get('КОММЕНТАРИЙ', ''))
        
        # 2. Обновляем дату доставки
        delivery_date_str = str(row.get('ДАТА_ДОСТАВКИ', ''))
        try:
            # Даты в Google Sheets обычно хранятся в формате YYYY-MM-DD
            date_obj = datetime.strptime(delivery_date_str, '%Y-%m-%d').date()
            st.session_state.k_delivery_date = date_obj
        except (ValueError, TypeError):
            st.session_state.k_delivery_date = get_default_delivery_date()


        # 3. Парсим состав заказа (ЗАКАЗ) и обновляем калькулятор
        order_text = str(row.get('ЗАКАЗ', ''))
        st.session_state.calculator_items = parse_order_text_to_items(order_text)
        
        st.success(f"✅ Данные заявки №**{order_number}** успешно загружены для корректировки.")
        st.warning("Внимание: при сохранении, эта заявка будет добавлена как новая. Удалите старую вручную!")


    except Exception as e:
        st.error(f"Ошибка при загрузке данных заявки: {e}")


def parse_order_text_to_items(order_text: str) -> List[Dict[str, Any]]:
    """Парсит строковое представление заказа (из Google Sheets) в список элементов калькулятора."""
    items = []
    
    # Регулярное выражение для поиска строк: НАИМЕНОВАНИЕ - КОЛИЧЕСТВО шт. (по ЦЕНА РУБ.)
    # Группы: (1: НАИМЕНОВАНИЕ), (2: КОЛИЧЕСТВО), (3: ЦЕНА)
    pattern = re.compile(r'(.+?) - (\d+)\s*шт\.\s*\(по\s*([\d\s,.]+)\s*РУБ\.\)')
    
    for line in order_text.split('\n'):
        match = pattern.search(line.strip())
        if match:
            name = match.group(1).strip()
            qty = int(match.group(2))
            # Удаляем пробелы и заменяем запятую на точку для преобразования в float
            price_str = match.group(3).replace(' ', '').replace(',', '.')
            try:
                price_per_unit = float(price_str)
            except ValueError:
                price_per_unit = 0.0 # Если цена не парсится, ставим 0
            
            items.append({
                'НАИМЕНОВАНИЕ': name,
                'КОЛИЧЕСТВО': qty,
                'ЦЕНА_ЗА_ЕД': price_per_unit,
                'СУММА': price_per_unit * qty
            })
    return items


# =========================================================
# 4. ИНИЦИАЛИЗАЦИЯ SESSION STATE
# =========================================================


# Инициализация ресурсов
price_df = load_price_list() 
orders_ws = get_orders_worksheet()
price_items = ["--- Выберите позицию ---"] + price_df['НАИМЕНОВАНИЕ'].tolist() if not price_df.empty else ["--- Прайс не загружен ---"]


if 'critical_error' not in st.session_state:
    st.session_state.critical_error = None
if 'calculator_items' not in st.session_state:
    st.session_state.calculator_items = []


if 'k_order_number' not in st.session_state:
    st.session_state.k_order_number = load_last_order_number()


if 'k_client_phone' not in st.session_state:
    st.session_state.k_client_phone = ""
if 'k_address' not in st.session_state:
    st.session_state.k_address = "" 
if 'k_comment' not in st.session_state:
    st.session_state.k_comment = "" 
    
if 'k_delivery_date' not in st.session_state:
    st.session_state.k_delivery_date = get_default_delivery_date()
    
if 'new_item_qty' not in st.session_state: 
    st.session_state['new_item_qty'] = 1 
    
if 'parsing_log' not in st.session_state:
    st.session_state.parsing_log = ""
    
if 'conversation_text_input' not in st.session_state:
    st.session_state.conversation_text_input = "" 


if 'new_item_select' not in st.session_state:
    st.session_state['new_item_select'] = price_items[0]


# =========================================================
# 5. ФУНКЦИИ ЛОГИКИ (ПАРСИНГ И ЗАПИСЬ)
# =========================================================


def parse_conversation(text: str):
    """Извлечение данных из текста переписки и обновление st.session_state."""
    
    st.session_state.parsing_log = f"--- ЛОГ ПАРСИНГА ({datetime.now().strftime('%H:%M:%S')}) ---\n"
    
    # ... [Логика парсинга телефона и даты остается прежней] ...
    
    # 1. Извлечение номера телефона
    phone_matches = re.findall(r'(?:(?:\+7|8|7)[\s(]?)?(\d{3})[\s)]?(\d{3})[-\s]?(\d{2})[-\s]?(\d{2})', text)
    
    st.session_state.parsing_log += f"Поиск телефонов (результаты): {phone_matches}\n"
    
    if phone_matches:
        phone_counts = {}
        for match in phone_matches:
            normalized_phone = "7" + "".join(match)
            if len(normalized_phone) == 11: 
                phone_counts[normalized_phone] = phone_counts.get(normalized_phone, 0) + 1
        
        if phone_counts:
            phone = max(phone_counts.items(), key=lambda item: item[1])[0]
            st.session_state['k_client_phone'] = phone 
            st.info(f"✅ Телефон клиента найден: **{phone}**")
            st.session_state.parsing_log += f"Определен основной телефон: {phone}\n"
        else:
             st.warning("⚠️ Телефон не найден. Пожалуйста, введите вручную.")
             st.session_state.parsing_log += f"Телефон не определен.\n"
    else:
        st.warning("⚠️ Телефон не найден. Пожалуйста, введите вручную.")
        st.session_state.parsing_log += f"Телефон не определен.\n"




    # 2. Извлечение номера заявки/счета
    order_match = re.search(r'(?:заявк[аи]|заказ|счет|№|номер)\s*[\W]*(\d+)', text, re.IGNORECASE)
    
    st.session_state.parsing_log += f"Поиск номера заявки (матч): {order_match.group(1) if order_match else 'None'}\n"


    if order_match:
        # ПЕРЕЗАПИСЫВАЕМ ТОЛЬКО ЕСЛИ КЛЮЧ НЕ БЫЛ ЗАГРУЖЕН ВРУЧНУЮ ДЛЯ РЕДАКТИРОВАНИЯ
        # В данном случае, просто перезаписываем, позволяя пользователю потом перебить
        st.session_state['k_order_number'] = order_match.group(1)
        st.info(f"✅ Номер Заявки найден и установлен: {order_match.group(1)}")
    else:
        # Если не найдено, оставляем автосгенерированный номер
        pass




    # 3. Извлечение даты доставки
    delivery_date = None
    relative_match = ""
    today = datetime.today().date()
    
    if re.search(r'послезавтра', text, re.IGNORECASE):
        delivery_date = today + timedelta(days=2)
        relative_match = "послезавтра (+2 дня)"
    elif re.search(r'завтра', text, re.IGNORECASE):
        delivery_date = today + timedelta(days=1)
        relative_match = "завтра (+1 день)"
    
    st.session_state.parsing_log += f"Поиск относительной даты: {relative_match or 'Нет'}\n"


    if not delivery_date:
        date_match = re.search(r'(\d{1,2})[./](\d{1,2})(?:[./](\d{2,4}))?', text)
        
        st.session_state.parsing_log += f"Поиск конкретной даты (матч): {date_match.groups() if date_match else 'None'}\n"
        
        if date_match:
            day, month, year_str = date_match.groups()
            current_year = today.year
            
            try:
                if year_str:
                    year = 2000 + int(year_str) if len(year_str) == 2 else int(year_str)
                else:
                    year = current_year
                    
                delivery_date = datetime(year, int(month), int(day)).date()
            except ValueError:
                st.session_state.parsing_log += f"Ошибка преобразования даты: {day}.{month}.{year_str or current_year}\n"
                pass
    
    if delivery_date:
        initial_date_str = delivery_date.strftime('%d.%m.%Y')
        year_corrected = False
        
        while delivery_date < today and delivery_date.year < today.year + 1:
            delivery_date = delivery_date.replace(year=delivery_date.year + 1)
            year_corrected = True


        if year_corrected:
            st.warning(f"⚠️ Обнаруженная дата ({initial_date_str}) была в прошлом. Год скорректирован на **{delivery_date.year}**.")
            st.session_state.parsing_log += f"Коррекция года: Исходная {initial_date_str}, Скорректирована на {delivery_date.year}\n"
            
        st.session_state['k_delivery_date'] = delivery_date
        st.info(f"✅ Дата Доставки найдена: **{delivery_date.strftime('%d.%m.%Y')}**")
    else:
        tomorrow = today + timedelta(days=1)
        st.session_state['k_delivery_date'] = tomorrow
        st.warning("⚠️ Дата доставки не найдена. Установлена на 'завтра'.")
        st.session_state.parsing_log += f"Дата доставки не найдена, установлена по умолчанию: {tomorrow.strftime('%d.%m.%Y')}\n"


    st.rerun() 


def save_data_to_gsheets(data_row: List[Any]) -> bool:
    """Добавляет строку данных на лист ЗАЯВКИ."""
    if orders_ws is None:
        st.error("Не удалось подключиться к листу для записи данных.")
        return False
    
    with st.spinner("⏳ Сохранение заявки в Google Sheets..."):
        try:
            orders_ws.append_row(data_row)
            return True
        except Exception as e:
            st.error(f"Ошибка записи в Google Sheets: {e}")
            return False


# =========================================================
# 6. ФУНКЦИИ КАЛЬКУЛЯТОРА И ИНТЕРФЕЙСА
# =========================================================


def add_item():
    """Добавляет выбранный товар в список в session_state."""
    selected_name = st.session_state['new_item_select']
    try:
        quantity = int(st.session_state['new_item_qty']) 
    except ValueError:
        st.error("Ошибка: Количество должно быть целым числом.")
        return
    
    if selected_name != "--- Выберите позицию ---" and quantity > 0:
        price_row = price_df[price_df['НАИМЕНОВАНИЕ'] == selected_name]
        
        if price_row.empty:
             st.error(f"Ошибка: позиция '{selected_name}' не найдена в прайс-листе.")
             return


        price = float(price_row.iloc[0]['ЦЕНА'])
        
        st.session_state.calculator_items.append({
            'НАИМЕНОВАНИЕ': selected_name,
            'КОЛИЧЕСТВО': quantity,
            'ЦЕНА_ЗА_ЕД': price,
            'СУММА': price * quantity
        })


        st.session_state['new_item_qty'] = 1
        st.session_state['new_item_select'] = price_items[0] 


def remove_item(index: int):
    """Удаляет позицию из списка по индексу."""
    if 0 <= index < len(st.session_state.calculator_items):
        st.session_state.calculator_items.pop(index)
    st.rerun()


def generate_whatsapp_url(target_phone: str, order_data: Dict[str, str], total_sum: float) -> str:
    """Генерирует ссылку на WhatsApp с предзаполненным текстом."""
    
    text = f"Здравствуйте! Пожалуйста, проверьте детали вашего заказа и подтвердите их:\n"
    text += f"🆔 Номер Заявки: {order_data['НОМЕР_ЗАЯВКИ']}\n"
    text += f"📞 Телефон: {order_data['ТЕЛЕФОН']}\n"
    text += f"📍 Адрес: {order_data['АДРЕС']}\n"
    text += f"🗓️ Дата Доставки: {order_data['ДАТА_ДОСТАВКИ']}\n"
    
    if order_data.get('КОММЕНТАРИЙ'):
        text += f"📝 Комментарий: {order_data['КОММЕНТАРИЙ']}\n"
        
    text += f"\n🛒 Состав Заказа:\n{order_data['ЗАКАЗ']}\n"
    text += f"💰 *ИТОГО: {total_sum:,.2f} РУБ.*\n"
    
    encoded_text = urllib.parse.quote(text)
    
    if not target_phone.startswith('+'):
        target_phone = '+' + target_phone
        
    return f"https://wa.me/{target_phone}?text={encoded_text}"




# =========================================================
# 7. ОСНОВНОЙ ИНТЕРФЕЙС STREAMLIT
# =========================================================


if st.session_state.critical_error:
    st.error(st.session_state.critical_error)
    st.stop() 


st.title("Ввод Новой Заявки CRM 📝")


# ----------------------------------------------------------------------------------------------------------------------
## Блок Редактирования/Парсинга
# ----------------------------------------------------------------------------------------------------------------------


with st.expander("🛠️ Загрузить для Редактирования / 🤖 Парсинг Переписки", expanded=True):
    col_order_num, col_button = st.columns([3, 2])
    
    with col_order_num:
         # Поле ввода номера заявки, привязанное к session_state
        st.text_input(
            "Номер Заявки / Счёта", 
            key='k_order_number_input_temp', # Используем временный ключ для ввода
            value=st.session_state.k_order_number if st.session_state.k_order_number else ""
        )
        
    with col_button:
        st.markdown(" ") # Отступ
        # Кнопка для загрузки данных по номеру
        if st.button("🔄 Получить данные по Заявке", type="secondary", use_container_width=True):
             # Переносим значение из временного ключа в основной перед загрузкой
             st.session_state.k_order_number = st.session_state.k_order_number_input_temp
             load_order_data(st.session_state.k_order_number)


    st.markdown("---")
    st.subheader("Вставьте текст переписки")
    
    conversation_text = st.text_area(
        "Вставьте полный текст переписки с клиентом сюда:",
        key='conversation_text_input',
        height=150
    )
    
    if st.button("🔍 Запустить Парсинг Данных", use_container_width=True):
        if conversation_text:
            parse_conversation(conversation_text)


    if st.session_state.parsing_log:
        st.caption("Лог Парсинга:")
        st.code(st.session_state.parsing_log, language='text')


st.markdown("---")


# ----------------------------------------------------------------------------------------------------------------------
## Форма Ввода Основных Данных
# ----------------------------------------------------------------------------------------------------------------------


st.subheader("Основные Данные Заявки")


col1, col2 = st.columns(2)


with col1:
    # Поле ввода номера заявки, привязанное к основному ключу
    st.text_input(
        "Номер Заявки (редактируемый)", 
        key='k_order_number',
        disabled=True # Делаем поле недоступным для прямого редактирования, только через кнопку/парсер
    )
    
    st.text_input(
        "Телефон Клиента (с 7)", 
        key='k_client_phone'
    )


with col2:
    st.date_input(
        "Дата Доставки",
        key='k_delivery_date',
        value=st.session_state.k_delivery_date, 
        min_value=datetime.today().date()
    )
    
    st.text_input(
        "Адрес Доставки", 
        key='k_address'
    )
    
st.text_area(
    "Комментарий / Примечание", 
    key='k_comment', 
    height=50
)


st.markdown("---")


# ----------------------------------------------------------------------------------------------------------------------
## Калькулятор Заказа
# ----------------------------------------------------------------------------------------------------------------------


st.subheader("Состав Заказа (Калькулятор)")


col_item, col_qty, col_add = st.columns([4, 1, 1])


with col_item:
    st.selectbox(
        "Выбор позиции", 
        price_items, 
        key='new_item_select',
        disabled=price_df.empty
    )


with col_qty:
    st.number_input(
        "Кол-во", 
        min_value=1, 
        step=1,
        key='new_item_qty' 
    )


with col_add:
    st.markdown(" ")
    disable_add = price_df.empty or st.session_state.get('new_item_select') == price_items[0]
    st.button("➕ Добавить", on_click=add_item, use_container_width=True, disabled=disable_add)


total_sum = 0
if st.session_state.calculator_items:
    
    df_items = pd.DataFrame(st.session_state.calculator_items)
    total_sum = df_items['СУММА'].sum() 
    
    st.dataframe(
        df_items[['НАИМЕНОВАНИЕ', 'КОЛИЧЕСТВО', 'ЦЕНА_ЗА_ЕД', 'СУММА']],
        column_config={
            'НАИМЕНОВАНИЕ': 'Товар',
            'КОЛИЧЕСТВО': 'Кол-во',
            'ЦЕНА_ЗА_ЕД': st.column_config.NumberColumn("Цена за ед.", format="%.2f РУБ."),
            'СУММА': st.column_config.NumberColumn("Сумма", format="%.2f РУБ."),
        },
        hide_index=True,
        use_container_width=True
    )
    
    st.markdown("##### Удаление позиций:")
    for i in range(len(st.session_state.calculator_items) - 1, -1, -1):
         item = st.session_state.calculator_items[i]
         col_name, col_sum, col_del = st.columns([5, 1.5, 0.5])
         with col_name:
             st.write(f"**{item['НАИМЕНОВАНИЕ']}** ({item['КОЛИЧЕСТВО']} шт.)") 
         with col_sum:
             st.write(f"**{item['СУММА']:,.2f} РУБ.**")
         with col_del:
             st.button("❌", key=f"del_{i}", on_click=remove_item, args=(i,))


    st.markdown(f"### 💰 **ИТОГО: {total_sum:,.2f} РУБ.**")
    
else:
    st.info("В заказе пока нет позиций. Добавьте товар.")


st.markdown("---")


# ----------------------------------------------------------------------------------------------------------------------
## Блок Отправки и Ссылок
# ----------------------------------------------------------------------------------------------------------------------


st.subheader("Завершение Заявки")


is_ready_to_send = (
    st.session_state.get('k_order_number') and 
    st.session_state.get('k_client_phone') and 
    st.session_state.get('k_address') and 
    st.session_state.calculator_items and
    is_valid_phone(st.session_state.get('k_client_phone', '')) 
)


order_details = "\n".join(
    [f"{item['НАИМЕНОВАНИЕ']} - {item['КОЛИЧЕСТВО']} шт. (по {item['ЦЕНА_ЗА_ЕД']:,.2f} РУБ.)" 
     for item in st.session_state.calculator_items]
)


if not is_ready_to_send:
    missing_fields = []
    if not st.session_state.get('k_order_number'): missing_fields.append("Номер Заявки")
    if not st.session_state.get('k_client_phone'): missing_fields.append("Телефон Клиента")
    elif not is_valid_phone(st.session_state.get('k_client_phone', '')): missing_fields.append("Телефон (неверный формат 7XXXXXXXXXX)")
    if not st.session_state.get('k_address'): missing_fields.append("Адрес Доставки")
    if not st.session_state.calculator_items: missing_fields.append("Состав Заказа")
    
    st.error(f"❌ Заявка не готова к сохранению! Необходимо заполнить: {', '.join(missing_fields)}")




# 1. Кнопка "Сохранить в CRM"
if st.button("💾 Сохранить Заявку в Google Sheets", disabled=not is_ready_to_send, type="primary", use_container_width=True):
    
    final_total_sum = float(total_sum) if not math.isnan(total_sum) else ""
    
    data_to_save = [
        datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        st.session_state.k_order_number,
        st.session_state.k_client_phone,
        st.session_state.k_address,
        st.session_state.k_delivery_date.strftime('%Y-%m-%d') if st.session_state.k_delivery_date else "",
        st.session_state.k_comment,
        order_details,
        final_total_sum 
    ]
    
    if save_data_to_gsheets(data_to_save):
        st.success(f"🎉 Заявка №{st.session_state.k_order_number} успешно сохранена! (Сохранена как **новая** строка)")
        
        clear_form_state()
        time.sleep(0.5)
        st.rerun() 


# 2. Блок генерации ссылки WhatsApp
if is_ready_to_send:
    
    whatsapp_data = {
        'НОМЕР_ЗАЯВКИ': st.session_state.k_order_number,
        'ТЕЛЕФОН': st.session_state.k_client_phone,
        'АДРЕС': st.session_state.k_address,
        'ДАТА_ДОСТАВКИ': st.session_state.k_delivery_date.strftime('%d.%m.%Y'),
        'КОММЕНТАРИЙ': st.session_state.k_comment,
        'ЗАКАЗ': order_details
    }
    
    final_total_sum = float(total_sum) if not math.isnan(total_sum) else 0.0
    
    whatsapp_url = generate_whatsapp_url(st.session_state.k_client_phone, whatsapp_data, final_total_sum)
    
    st.markdown("---")
    st.markdown(f"**Ссылка для подтверждения клиенту ({st.session_state.k_client_phone}):**")
    
    st.markdown(
        f'<a href="{whatsapp_url}" target="_blank">'
        f'<button style="background-color:#25D366;color:white;padding:10px 20px;border:none;border-radius:5px;cursor:pointer;width:100%;">'
        f'💬 Открыть WhatsApp с Заказом'
        f'</button></a>',
        unsafe_allow_html=True
    )
    st.caption("Кликните, чтобы открыть чат с предзаполненным сообщением.")