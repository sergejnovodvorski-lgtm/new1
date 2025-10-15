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


def load_last_order_number_safe() -> str:
    """Безопасная обертка для load_last_order_number, чтобы не вызывать ошибку на старте."""
    try:
        return load_last_order_number() 
    except Exception:
        return "1001"


def clear_form_state():
    """Сброс всех полей после успешной отправки."""
    # Сохраняем режим работы
    current_mode = st.session_state.get('app_mode', 'new')
    
    # Полный сброс состояния
    keys_to_keep = ['app_mode', 'mode_selector_value', 'critical_error']
    new_state = {key: st.session_state.get(key) for key in keys_to_keep}
    
    st.session_state.clear()
    st.session_state.update(new_state)
    
    # Восстанавливаем режим и устанавливаем значения по умолчанию
    st.session_state.calculator_items = []
    st.session_state.k_order_number = load_last_order_number_safe()
    st.session_state.k_delivery_date = get_default_delivery_date()
    st.session_state.k_target_row_index = None
    st.session_state.do_clear_form = False
    st.session_state.last_success_message = None
    
    # Инициализируем поля ввода
    st.session_state.k_client_phone = ""
    st.session_state.k_address = ""
    st.session_state.k_comment = ""
    st.session_state.conversation_text_input = ""
    st.session_state.k_order_number_input = st.session_state.k_order_number if current_mode == 'new' else ""
    st.session_state.parsing_log = ""
    st.session_state.new_item_qty = 1


def is_valid_phone(phone: str) -> str:
    """Нормализует телефон к формату 7XXXXXXXXXX. Возвращает нормализованный номер или пустую строку."""
    normalized = re.sub(r'\D', '', phone) # Удаляем все не-цифры
    
    # Если номер начинается с 8, заменяем на 7
    if normalized.startswith('8') and len(normalized) == 11:
        normalized = '7' + normalized[1:]


    # Проверка, соответствует ли телефон формату 7XXXXXXXXXX
    if len(normalized) == 11 and normalized.startswith('7'):
        return normalized
        
    return "" # Возвращаем пустую строку, если невалиден


def switch_mode():
    """Переключает режим работы и обновляет состояние формы."""
    new_mode = 'new' if st.session_state.mode_selector_value == 'Новая заявка' else 'edit'
    
    if st.session_state.get('app_mode') != new_mode:
        # Сохраняем необходимые значения перед очисткой
        mode_selector = st.session_state.mode_selector_value
        
        # Очищаем состояние
        keys_to_keep = ['mode_selector_value', 'critical_error']
        saved_state = {key: st.session_state.get(key) for key in keys_to_keep}
        
        st.session_state.clear()
        st.session_state.update(saved_state)
        
        # Устанавливаем новый режим
        st.session_state.app_mode = new_mode
        
        # Инициализируем состояние для нового режима
        if new_mode == 'new':
            st.session_state.k_order_number = load_last_order_number_safe()
            st.session_state.k_order_number_input = st.session_state.k_order_number
        else:
            st.session_state.k_order_number_input = ""
            
        st.session_state.calculator_items = []
        st.session_state.k_delivery_date = get_default_delivery_date()
        st.session_state.k_target_row_index = None
        st.session_state.k_client_phone = ""
        st.session_state.k_address = ""
        st.session_state.k_comment = ""
        st.session_state.conversation_text_input = ""
        st.session_state.parsing_log = ""
        st.session_state.new_item_qty = 1
        
    st.rerun()


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
    Загружает данные заявки по номеру из Google Sheets и обновляет st.session_state,
    сохраняя индекс строки для последующего обновления.
    
    ИСПРАВЛЕНО: Теперь ищет последнюю (самую свежую) запись, чтобы избежать редактирования 
    старых дубликатов, если такие есть.
    """
    orders_ws = get_orders_worksheet()
    if not orders_ws:
        st.error("Не удалось подключиться к базе данных.")
        return False 


    try:
        # Получаем все записи (кроме заголовка)
        data = orders_ws.get_all_records()
        df = pd.DataFrame(data)
        
        # Фильтруем по номеру заявки
        target_rows = df[df['НОМЕР_ЗАЯВКИ'].astype(str) == order_number]
        
        if target_rows.empty:
            st.warning(f"⚠️ Заявка с номером **{order_number}** не найдена.")
            st.session_state.k_target_row_index = None 
            return False


        # --- КЛЮЧЕВОЕ ИЗМЕНЕНИЕ ДЛЯ ПЕРЕЗАПИСИ: Берем ПОСЛЕДНЮЮ запись ---
        # Индекс в исходном DataFrame (начиная с 0)
        row_index_in_df = target_rows.index[-1] 
        # Сама строка
        row = target_rows.iloc[-1].to_dict()
        
        # 1. Сохранение номера строки для обновления (индекс в gspread = индекс в df + 2)
        # +2: 1 заголовок + 1 из-за 0-индексации
        gspread_row_index = row_index_in_df + 2 
        st.session_state.k_target_row_index = gspread_row_index


        # 2. Обновляем основные поля формы
        st.session_state.k_order_number = str(row.get('НОМЕР_ЗАЯВКИ', ''))
        st.session_state.k_client_phone = str(row.get('ТЕЛЕФОН', ''))
        st.session_state.k_address = str(row.get('АДРЕС', ''))
        st.session_state.k_comment = str(row.get('КОММЕНТАРИЙ', ''))
        
        # 3. Обновляем дату доставки
        delivery_date_str = str(row.get('ДАТА_ДОСТАВКИ', ''))
        try:
            date_obj = datetime.strptime(delivery_date_str, '%Y-%m-%d').date()
            st.session_state.k_delivery_date = date_obj
        except (ValueError, TypeError):
            st.session_state.k_delivery_date = get_default_delivery_date()


        # 4. Парсим состав заказа
        order_text = str(row.get('ЗАКАЗ', ''))
        st.session_state.calculator_items = parse_order_text_to_items(order_text)
        
        st.success(f"✅ Данные заявки №**{order_number}** успешно загружены для корректировки. (Строка {gspread_row_index})")
        st.warning("Внимание: При сохранении **существующая заявка будет перезаписана**!")
        
        return True 


    except Exception as e:
        st.error(f"Ошибка при загрузке данных заявки: {e}")
        return False


def parse_order_text_to_items(order_text: str) -> List[Dict[str, Any]]:
    items = []
    pattern = re.compile(r'(.+?) - (\d+)\s*шт\.\s*\(по\s*([\d\s,.]+)\s*РУБ\.\)')
    
    for line in order_text.split('\n'):
        match = pattern.search(line.strip())
        if match:
            name = match.group(1).strip()
            qty = int(match.group(2))
            price_str = match.group(3).replace(' ', '').replace(',', '.')
            try:
                price_per_unit = float(price_str)
            except ValueError:
                price_per_unit = 0.0
            
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


# Сначала загружаем данные
price_df = load_price_list() 
orders_ws = get_orders_worksheet()
price_items = ["--- Выберите позицию ---"] + price_df['НАИМЕНОВАНИЕ'].tolist() if not price_df.empty else ["--- Прайс не загружен ---"]


# Инициализация session_state с проверкой существующих значений
if 'critical_error' not in st.session_state:
    st.session_state.critical_error = None
    
if 'app_mode' not in st.session_state:
    st.session_state.app_mode = 'new' 
    
if 'mode_selector_value' not in st.session_state:
    st.session_state.mode_selector_value = 'Новая заявка'


if 'calculator_items' not in st.session_state:
    st.session_state.calculator_items = []


if 'k_target_row_index' not in st.session_state:
    st.session_state.k_target_row_index = None 
    
if 'do_clear_form' not in st.session_state:
    st.session_state.do_clear_form = False


if 'last_success_message' not in st.session_state:
    st.session_state.last_success_message = None 


if 'k_order_number' not in st.session_state:
    st.session_state.k_order_number = load_last_order_number_safe()


if 'k_order_number_input' not in st.session_state:
    st.session_state.k_order_number_input = st.session_state.k_order_number if st.session_state.app_mode == 'new' else "" 
    
if 'k_client_phone' not in st.session_state:
    st.session_state.k_client_phone = ""
    
if 'k_address' not in st.session_state:
    st.session_state.k_address = "" 
    
if 'k_comment' not in st.session_state:
    st.session_state.k_comment = "" 
    
if 'k_delivery_date' not in st.session_state:
    st.session_state.k_delivery_date = get_default_delivery_date()
    
if 'new_item_qty' not in st.session_state: 
    st.session_state.new_item_qty = 1 
    
if 'parsing_log' not in st.session_state:
    st.session_state.parsing_log = ""
    
if 'conversation_text_input' not in st.session_state:
    st.session_state.conversation_text_input = "" 
    
if 'new_item_select' not in st.session_state:
    st.session_state.new_item_select = price_items[0]


# =========================================================
# 5. ФУНКЦИИ ЛОГИКИ (ПАРСИНГ И ЗАПИСЬ)
# =========================================================


def parse_conversation(text: str):
    """Извлечение данных из текста переписки и обновление st.session_state."""
    
    st.session_state.parsing_log = f"--- ЛОГ ПАРСИНГА ({datetime.now().strftime('%H:%M:%S')}) ---\n"
    
    loaded_data = False 


    # 1. Извлечение номера телефона
    phone_matches_raw = re.findall(r'(\d{7,11})', text) 
    phone_counts = {}
    
    st.session_state.parsing_log += f"Поиск телефонов (результаты): {phone_matches_raw}\n"
    
    for raw_phone in phone_matches_raw:
        normalized_phone = is_valid_phone(raw_phone)
        
        if normalized_phone:
            phone_counts[normalized_phone] = phone_counts.get(normalized_phone, 0) + 1
    
    if phone_counts:
        phone = max(phone_counts.items(), key=lambda item: item[1])[0]
        st.session_state.k_client_phone = phone 
        st.info(f"✅ Телефон клиента найден: **{phone}**")
        st.session_state.parsing_log += f"Определен основной телефон: {phone}\n"
    else:
         st.warning("⚠️ Телефон не найден. Пожалуйста, введите вручную.")
         st.session_state.parsing_log += f"Телефон не определен.\n"


    # 2. Извлечение номера заявки/счета
    order_match = re.search(r'(?:заявк[аи]|заказ|счет|№|номер)\s*[\W]*(\d+)', text, re.IGNORECASE)
    
    st.session_state.parsing_log += f"Поиск номера заявки (матч): {order_match.group(1) if order_match else 'None'}\n"


    if order_match and st.session_state.app_mode == 'edit':
        found_order_num = order_match.group(1)
        st.session_state.k_order_number_input = found_order_num
        st.session_state.k_order_number = found_order_num
        
        if load_order_data(found_order_num):
             loaded_data = True
             st.info(f"✅ Номер Заявки найден и установлен: {found_order_num}. Данные загружены.")
             return
    elif order_match and st.session_state.app_mode == 'new':
        st.info(f"💡 Обнаружен номер {order_match.group(1)}, но в режиме 'Новая заявка' он игнорируется.")
        
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
            
        st.session_state.k_delivery_date = delivery_date
        st.info(f"✅ Дата Доставки найдена: **{delivery_date.strftime('%d.%m.%Y')}**")
    else:
        tomorrow = today + timedelta(days=1)
        st.session_state.k_delivery_date = tomorrow
        st.warning("⚠️ Дата доставки не найдена. Установлена на 'завтра'.")
        st.session_state.parsing_log += f"Дата доставки не найдена, установлена по умолчанию: {tomorrow.strftime('%d.%m.%Y')}\n"


    st.rerun()


def save_data_to_gsheets(data_row: List[Any]) -> bool:
    """Обновляет существующую строку или добавляет новую в лист ЗАЯВКИ."""
    if orders_ws is None:
        st.error("Не удалось подключиться к листу для записи данных.")
        return False
    
    row_index = st.session_state.k_target_row_index
    
    with st.spinner(f"⏳ {'Обновление' if row_index else 'Сохранение'} заявки в Google Sheets..."):
        try:
            if row_index and isinstance(row_index, int) and row_index > 1:
                # ОБНОВЛЕНИЕ СУЩЕСТВУЮЩЕЙ СТРОКИ
                orders_ws.update(f'A{row_index}:{gspread.utils.rowcol_to_a1(row_index, len(data_row))}', [data_row])
                return True
            else:
                # ДОБАВЛЕНИЕ НОВОЙ СТРОКИ
                orders_ws.append_row(data_row)
                return True
        except Exception as e:
            st.error(f"Ошибка {'обновления' if row_index else 'записи'} в Google Sheets: {e}")
            return False


def handle_save_and_clear(data_to_save: List[Any], is_update: bool):
    """Обработчик сохранения данных."""
    if save_data_to_gsheets(data_to_save):
        success_message = f"🎉 Заявка №{st.session_state.k_order_number} успешно {'перезаписана' if is_update else 'сохранена'}!"
        st.session_state.last_success_message = success_message
        st.session_state.do_clear_form = True


# =========================================================
# 6. ФУНКЦИИ КАЛЬКУЛЯТОРА И ИНТЕРФЕЙСА
# =========================================================


def add_item():
    """Добавляет выбранный товар в список в session_state."""
    selected_name = st.session_state.new_item_select
    try:
        quantity = int(st.session_state.new_item_qty) 
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


        st.session_state.new_item_qty = 1
        st.session_state.new_item_select = price_items[0]


def remove_item(index: int):
    """Удаляет позицию из списка по индексу."""
    if 0 <= index < len(st.session_state.calculator_items):
        st.session_state.calculator_items.pop(index)


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
    
    normalized_phone = is_valid_phone(target_phone)
    if not normalized_phone:
        target_phone_final = MANAGER_WHATSAPP_PHONE
    else:
        target_phone_final = '+' + normalized_phone 
        
    return f"https://wa.me/{target_phone_final}?text={encoded_text}"


# =========================================================
# 7. ОСНОВНОЙ ИНТЕРФЕЙС STREAMLIT
# =========================================================


if st.session_state.critical_error:
    st.error(st.session_state.critical_error)
    st.stop() 


st.title("Ввод Новой Заявки CRM 📝")


# Обработка очистки формы в безопасном месте
if st.session_state.do_clear_form:
    if st.session_state.get('last_success_message'):
        st.success(st.session_state.last_success_message)
        st.session_state.last_success_message = None
        
    clear_form_state()
    st.rerun()


# ----------------------------------------------------------------------------------------------------------------------
## Блок Выбора Режима и Парсинга
# ----------------------------------------------------------------------------------------------------------------------


st.subheader("Выбор Режима Работы")


# Радио-кнопка для выбора режима
st.radio(
    "Выберите действие:",
    options=['Новая заявка', 'Редактировать существующую'],
    index=0 if st.session_state.app_mode == 'new' else 1,
    key='mode_selector_value',
    horizontal=True,
    on_change=switch_mode
)


mode_text = (
    "➕ **Режим Создания Новой Заявки**" 
    if st.session_state.app_mode == 'new' 
    else "🔄 **Режим Редактирования/Перезаписи**"
)
st.info(mode_text)


# --- Блок Номера Заявки ---
col_num, col_btn = st.columns([3, 1])


with col_num:
    # Используем key='k_order_number_input' для поля ввода номера
    st.text_input(
        "Номер Заявки / Счёта", 
        key='k_order_number_input',
        value=st.session_state.k_order_number if st.session_state.app_mode == 'new' else st.session_state.k_order_number_input,
        disabled=st.session_state.app_mode == 'new', 
        help="В режиме 'Новая' номер генерируется. В режиме 'Редактировать' введите номер и нажмите кнопку."
    )
    
with col_btn:
    st.markdown(" ") 
    if st.session_state.app_mode == 'edit':
        if st.button("🔄 Загрузить Заявку", type="secondary", use_container_width=True):
            # При загрузке k_order_number обновляется из k_order_number_input
            st.session_state.k_order_number = st.session_state.k_order_number_input
            load_order_data(st.session_state.k_order_number) 
    else:
        if st.button("🧼 Очистить Форму", type="secondary", use_container_width=True):
            st.session_state.do_clear_form = True


st.markdown("---")


# --- Блок Парсинга ---
with st.expander("🤖 Парсинг Переписки (извлекает телефон, дату и заказ)", expanded=False):
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
    st.text_input(
        "Номер Заявки (текущий)", 
        key='k_order_number_display',
        value=st.session_state.k_order_number,
        disabled=True 
    )
    
    st.text_input(
        "Телефон Клиента (с 7)", 
        key='k_client_phone',
        value=st.session_state.k_client_phone
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
        key='k_address',
        value=st.session_state.k_address
    )
    
st.text_area(
    "Комментарий / Примечание", 
    key='k_comment', 
    value=st.session_state.k_comment,
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
        disabled=price_df.empty,
        index=price_items.index(st.session_state.new_item_select) if st.session_state.new_item_select in price_items else 0
    )


with col_qty:
    st.number_input(
        "Кол-во", 
        min_value=1, 
        step=1,
        key='new_item_qty',
        value=st.session_state.new_item_qty
    )


with col_add:
    st.markdown(" ")
    disable_add = price_df.empty or st.session_state.new_item_select == price_items[0]
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
             if st.button("❌", key=f"del_{i}", on_click=remove_item, args=(i,)):
                 st.rerun()


    st.markdown(f"### 💰 **ИТОГО: {total_sum:,.2f} РУБ.**")
    
else:
    st.info("В заказе пока нет позиций. Добавьте товар.")


st.markdown("---")


# ----------------------------------------------------------------------------------------------------------------------
## Блок Отправки и Ссылок
# ----------------------------------------------------------------------------------------------------------------------


st.subheader("Завершение Заявки")


valid_phone = is_valid_phone(st.session_state.k_client_phone)


is_ready_to_send = (
    st.session_state.k_order_number and 
    valid_phone and 
    st.session_state.k_address and 
    st.session_state.calculator_items 
)


# --- ДОБАВЛЕННАЯ ЛОГИКА ДЛЯ ПРЕДОТВРАЩЕНИЯ ДУБЛИРОВАНИЯ В РЕЖИМЕ РЕДАКТИРОВАНИЯ ---
can_save = is_ready_to_send


if st.session_state.app_mode == 'edit' and not st.session_state.k_target_row_index:
     can_save = False
     if is_ready_to_send: # Поля заполнены, но заявка не загружена
         st.error("❌ В режиме 'Редактировать' необходимо сначала загрузить заявку по номеру, нажав 'Загрузить Заявку'.")
# ------------------------------------------------------------------------------------


order_details = "\n".join(
    [f"{item['НАИМЕНОВАНИЕ']} - {item['КОЛИЧЕСТВО']} шт. (по {item['ЦЕНА_ЗА_ЕД']:,.2f} РУБ.)" 
     for item in st.session_state.calculator_items]
)


if not is_ready_to_send and st.session_state.app_mode == 'new':
    missing_fields = []
    if not st.session_state.k_order_number: missing_fields.append("Номер Заявки")
    if not st.session_state.k_client_phone: missing_fields.append("Телефон Клиента")
    elif not valid_phone: missing_fields.append("Телефон (неверный формат 7XXXXXXXXXX)")
    if not st.session_state.k_address: missing_fields.append("Адрес Доставки")
    if not st.session_state.calculator_items: missing_fields.append("Состав Заказа")
    
    if missing_fields:
        st.error(f"❌ Заявка не готова к сохранению! Необходимо заполнить: {', '.join(missing_fields)}")


# 1. Подготовка данных
button_label = "💾 Перезаписать Заявку" if st.session_state.k_target_row_index else "💾 Сохранить Новую Заявку"
button_type = "primary"


data_to_save = [
    datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    st.session_state.k_order_number,
    valid_phone, 
    st.session_state.k_address,
    st.session_state.k_delivery_date.strftime('%Y-%m-%d') if st.session_state.k_delivery_date else "",
    st.session_state.k_comment,
    order_details,
    float(total_sum) if not math.isnan(total_sum) else 0.0
]


is_update = bool(st.session_state.k_target_row_index)


# 2. Кнопка "Сохранить в CRM"
# Используем can_save для проверки возможности сохранения
if st.button(button_label, disabled=not can_save, type=button_type, use_container_width=True):
    handle_save_and_clear(data_to_save, is_update)


# 3. Блок генерации ссылки WhatsApp
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
    
    whatsapp_url = generate_whatsapp_url(valid_phone, whatsapp_data, final_total_sum)
    
    st.markdown("---")
    st.markdown(f"**Ссылка для подтверждения клиенту ({valid_phone}):**")
    
    st.markdown(
        f'<a href="{whatsapp_url}" target="_blank">'
        f'<button style="background-color:#25D366;color:white;padding:10px 20px;border:none;border-radius:5px;cursor:pointer;width:100%;">'
        f'💬 Открыть WhatsApp с Заказом'
        f'</button></a>',
        unsafe_allow_html=True
    )
    st.caption("Кликните, чтобы открыть чат с предзаполненным сообщением.")