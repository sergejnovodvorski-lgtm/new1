import streamlit as st
import gspread
import pandas as pd
import re
from datetime import datetime, timedelta, time
import urllib.parse
from typing import List, Dict, Any
import math


# ======
# КОНСТАНТЫ И НАСТРОЙКИ
# ======
SPREADSHEET_NAME = "Start"
WORKSHEET_NAME_ORDERS = "ЗАЯВКИ"
WORKSHEET_NAME_PRICE = "ПРАЙС"


# ВАЖНО: Колонка в Google Sheets называется "ДАТА ДОСТАВКИ" (с пробелом)
DELIVERY_DATE_COLUMN_NAME = "ДАТА ДОСТАВКИ" 


EXPECTED_HEADERS = [
    "ДАТА_ВВОДА",
    "НОМЕР_ЗАЯВКИ",
    "ТЕЛЕФОН",
    "АДРЕС",
    DELIVERY_DATE_COLUMN_NAME, 
    "КОММЕНТАРИЙ",
    "ЗАКАЗ",
    "СУММА"
]


# Индекс столбца для сортировки/вставки: ДАТА ДОСТАВКИ (Е)
DELIVERY_DATE_COLUMN_INDEX = 5


MANAGER_WHATSAPP_PHONE = "79000000000"
TIME_STEP_SECONDS = 1800


# --- ФОРМАТЫ ДАТЫ ---
SHEET_DATETIME_FORMAT = '%d.%m.%Y %H:%M:%S'
PARSE_DATETIME_FORMAT = '%d.%m.%Y %H:%M:%S'
# Исправлено %М на %M для минут
DISPLAY_DATE_FORMAT = '%d.%m.%Y %H:%M' 


st.set_page_config(
    page_title="CRM: Ввод Новой Заявки",
    layout="wide",
    initial_sidebar_state="expanded"
)


# ==================
# БАЗОВЫЕ ФУНКЦИИ (Работа с данными и Google Sheets)
# ==================


@st.cache_resource(ttl=3600)
def get_gsheet_client():
    if "gcp_service_account" not in st.secrets:
        st.error("Секрет 'gcp_service_account' не найден. Проверьте конфигурацию secrets.toml.")
        return None
    try:
        return gspread.service_account_from_dict(st.secrets["gcp_service_account"])
    except Exception as e:
        st.error(f"Ошибка аутентификации: {e}")
        return None


@st.cache_resource
def get_orders_worksheet():
    gc = get_gsheet_client()
    if not gc:
        return None
    try:
        sh = gc.open(SPREADSHEET_NAME)
        worksheet = sh.worksheet(WORKSHEET_NAME_ORDERS)
        current_headers = worksheet.row_values(1)
        if current_headers != EXPECTED_HEADERS:
            worksheet.update('A1:H1', [EXPECTED_HEADERS])
        return worksheet
    except Exception as e:
        st.error(f"Ошибка доступа к листу '{WORKSHEET_NAME_ORDERS}': {e}")
        return None


@st.cache_data(ttl="1h")
def load_all_orders():
    orders_ws = get_orders_worksheet()
    if not orders_ws:
        return pd.DataFrame()
    try:
        data = orders_ws.get_all_records()
        df = pd.DataFrame(data)
        return df
    except Exception as e:
        st.error(f"Ошибка загрузки списка заявок: {e}")
        return pd.DataFrame()


@st.cache_data(ttl="1h")
def load_price_list():
    gc = get_gsheet_client()
    if not gc:
        return pd.DataFrame()
    try:
        sh = gc.open(SPREADSHEET_NAME)
        worksheet = sh.worksheet(WORKSHEET_NAME_PRICE)
        data = worksheet.get_all_records()
        df = pd.DataFrame(data)


        if 'НАИМЕНОВАНИЕ' not in df.columns or 'ЦЕНА' not in df.columns:
            st.error("В прайсе отсутствуют обязательные столбцы: 'НАИМЕНОВАНИЕ' или 'ЦЕНА'.")
            return pd.DataFrame()


        df['ЦЕНА'] = pd.to_numeric(df['ЦЕНА'], errors='coerce')
        df.dropna(subset=['ЦЕНА'], inplace=True)
        return df
    except Exception as e:
        st.error(f"Ошибка загрузки прайса: {e}")
        return pd.DataFrame()


def is_valid_phone(phone: str) -> str:
    normalized = re.sub(r'\D', '', phone)
    if normalized.startswith('8') and len(normalized) == 11:
        normalized = '7' + normalized[1:]
    if len(normalized) == 11 and normalized.startswith('7'):
        return normalized
    return ""


def get_default_delivery_date():
    return datetime.today().date() + timedelta(days=1)


def get_default_delivery_time():
    return time(10, 0)


# ======
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ (Логика приложения)
# ===================


def generate_next_order_number():
    """Генерирует следующий номер заявки"""
    try:
        df = load_all_orders()
        if not df.empty and 'НОМЕР_ЗАЯВКИ' in df.columns:
            order_numbers = [int(n) for n in df['НОМЕР_ЗАЯВКИ'] if str(n).isdigit()]
            return str(max(order_numbers) + 1) if order_numbers else "1001"
        else:
            return "1001"
    except:
        return "1001"


def parse_order_text_to_items(order_text: str) -> List[Dict[str, Any]]:
    items = []
    # Паттерн: Наименование - Количество шт. (по Цена РУБ.) | Комментарий
    pattern = re.compile(r'(.+?) - (\d+)\s*шт\.\s*\(по\s*([\d\s,.]+)\s*РУБ\.\)(?:\s*\|\s*(.*))?')


    for line in order_text.split('\n'):
        match = pattern.search(line.strip())
        if match:
            name = match.group(1).strip()
            qty = int(match.group(2))
            price_str_raw = match.group(3)
            
            # Более надежный парсинг цены
            price_str_cleaned = price_str_raw.replace(' ', "").replace(',', '.')
            price_str = re.sub(r'[^\d.]', '', price_str_cleaned)
            
            comment = match.group(4).strip() if match.group(4) else ""
            
            try:
                price_per_unit = float(price_str)
            except ValueError:
                price_per_unit = 0.0 


            items.append({
                'НАИМЕНОВАНИЕ': name,
                'КОЛИЧЕСТВО': qty,
                'ЦЕНА_ЗА_ЕД': price_per_unit,
                'СУММА': price_per_unit * qty,
                'КОММЕНТАРИЙ_ПОЗИЦИИ': comment
            })
    return items


def get_insert_index(new_delivery_date_str: str, orders_ws) -> int:
    if not orders_ws: return 2
    try:
        data_col = orders_ws.col_values(DELIVERY_DATE_COLUMN_INDEX)[1:]
    except Exception:
        return 2
    
    if not data_col: return 2
    
    try:
        new_date = datetime.strptime(new_delivery_date_str, PARSE_DATETIME_FORMAT)
    except ValueError:
        return 2


    for i, date_str in enumerate(data_col):
        try:
            existing_date = datetime.strptime(date_str, PARSE_DATETIME_FORMAT)
            if new_date <= existing_date:
                return i + 2
        except ValueError:
            continue
            
    return len(data_col) + 2


def save_order_data(data_row: List[Any], orders_ws) -> bool:
    if not orders_ws: return False
    try:
        new_delivery_date_str = data_row[4]
        insert_index = get_insert_index(new_delivery_date_str, orders_ws)
        orders_ws.insert_row(data_row, index=insert_index)
        load_all_orders.clear()
        return True
    except Exception as e:
        st.error(f"Ошибка сохранения заявки: {e}")
        return False


def update_order_data(order_number: str, data_row: List[Any], orders_ws) -> bool:
    if not orders_ws: return False
    try:
        col_values = orders_ws.col_values(2)
        target_gspread_row_index = -1
        for i in range(len(col_values) - 1, 0, -1):
            if str(col_values[i]) == order_number:
                target_gspread_row_index = i + 1
                break


        if target_gspread_row_index == -1:
            st.error(f"Заявка с номером {order_number} не найдена в таблице.")
            return False


        orders_ws.update(f'A{target_gspread_row_index}:H{target_gspread_row_index}',
                         [data_row])
        load_all_orders.clear()
        return True
    except Exception as e:
        st.error(f"Ошибка обновления заявки: {e}")
        return False


def generate_whatsapp_url(target_phone: str, order_data: Dict[str, str], total_sum: float) -> str:
    text = f"Здравствуйте! Пожалуйста, проверьте детали вашего заказа:\n\n"
    text += f"*Номер Заявки:* {order_data['НОМЕР_ЗАЯВКИ']}\n"
    text += f"*Телефон:* {order_data['ТЕЛЕФОН']}\n"
    text += f"*Адрес:* {order_data['АДРЕС']}\n"
    text += f"*Дата и Время Доставки:* {order_data[DELIVERY_DATE_COLUMN_NAME]}\n" 
    if order_data.get('КОММЕНТАРИЙ'):
        text += f"*Комментарий к заказу (общий):* {order_data['КОММЕНТАРИЙ']}\n"
    
    text += f"\n*Состав Заказа:*\n{order_data['ЗАКАЗ']}\n\n"
    text += f"*ИТОГО: {total_sum:,.2f} РУБ.*\n\n"
    text += "Пожалуйста, подтвердите заказ или укажите необходимые изменения."
    
    encoded_text = urllib.parse.quote(text)
    normalized_phone = is_valid_phone(target_phone)
    if not normalized_phone:
        target_phone_final = MANAGER_WHATSAPP_PHONE
    else:
        target_phone_final = normalized_phone
        
    return f"https://wa.me/{target_phone_final}?text={encoded_text}"


def format_datetime_for_display(dt_str):
    """Форматирует дату-время для отображения"""
    if not isinstance(dt_str, str):
        return str(dt_str) 
        
    try:
        # Пробуем распарсить в формате сохранения
        dt = datetime.strptime(dt_str, PARSE_DATETIME_FORMAT)
        return dt.strftime(DISPLAY_DATE_FORMAT)
    except ValueError:
        try:
            # Пробуем альтернативный формат, если основной не сработал
            dt = datetime.strptime(dt_str, '%d.%m.%Y %H:%M')
            return dt.strftime(DISPLAY_DATE_FORMAT)
        except ValueError:
            # Если не удалось распарсить, возвращаем исходную строку
            return dt_str


# ============================
# ОСНОВНАЯ ЛОГИКА ПРИЛОЖЕНИЯ
# ============================


def main():
    # Инициализация основного состояния
    if 'app_mode' not in st.session_state:
        st.session_state.app_mode = 'new'
    if 'calculator_items' not in st.session_state:
        st.session_state.calculator_items = []
    if 'last_success_message' not in st.session_state:
        st.session_state.last_success_message = None
    if 'form_reset_trigger' not in st.session_state:
        st.session_state.form_reset_trigger = False
    if 'loaded_order_data' not in st.session_state:
        st.session_state.loaded_order_data = None
    if 'form_key' not in st.session_state:
        st.session_state.form_key = 0


    # Обработка сброса формы
    if st.session_state.form_reset_trigger:
        st.session_state.form_reset_trigger = False
        st.session_state.app_mode = 'new'
        st.session_state.calculator_items = []
        st.session_state.last_success_message = None
        st.session_state.loaded_order_data = None
        st.session_state.form_key += 1 
        st.rerun()


    # Загрузка данных
    price_df = load_price_list()
    orders_ws = get_orders_worksheet()
    
    price_items = ["--- Выберите позицию ---"] + price_df['НАИМЕНОВАНИЕ'].tolist() if not price_df.empty else ["--- Прайс не загружен ---"]


    st.title("CRM: Управление Заявками")


    # Обработка успешного сообщения
    if st.session_state.last_success_message:
        st.success(st.session_state.last_success_message)
        st.session_state.last_success_message = None


    # ====================
    # ГЛАВНОЕ РАЗДЕЛЕНИЕ НА ВКЛАДКИ
    # ====================
    tab_order_entry, tab_order_list = st.tabs(["Ввод/Редактирование Заявки", "Список Заявок"])


    # ====================
    # ВКЛАДКА 1: ВВОД/РЕДАКТИРОВАНИЕ ЗАЯВКИ
    # ====================
    with tab_order_entry:
        st.subheader("Выбор Режима Работы")
        
        mode = st.radio(
            "Выберите действие:",
            ['Новая заявка', 'Редактировать существующую'],
            horizontal=True,
            key='mode_selector'
        )


        if mode == 'Новая заявка' and st.session_state.app_mode != 'new':
            st.session_state.app_mode = 'new'
            st.session_state.calculator_items = []
            st.session_state.loaded_order_data = None
            st.session_state.form_key += 1
            st.rerun()


        elif mode == 'Редактировать существующую' and st.session_state.app_mode != 'edit':
            st.session_state.app_mode = 'edit'
            st.session_state.calculator_items = []
            st.session_state.loaded_order_data = None
            st.session_state.form_key += 1
            st.rerun()
            
        st.info("**Режим Создания Новой Заявки**" if st.session_state.app_mode == 'new'
                else "**Режим Редактирования/Перезаписи**")
        
        # ====================
        # ПОИСК СУЩЕСТВУЮЩЕЙ ЗАЯВКИ
        # ====================
        if st.session_state.app_mode == 'edit':
            st.subheader("Поиск заявки для редактирования")
            search_number = st.text_input("Введите номер заявки для поиска:", key='search_input')
            
            if st.button("🔎 Найти и загрузить заявку", use_container_width=True):
                if search_number and orders_ws:
                    try:
                        df = load_all_orders()
                        target_rows = df[df['НОМЕР_ЗАЯВКИ'].astype(str) == search_number]


                        if not target_rows.empty:
                            row = target_rows.iloc[-1].to_dict()


                            st.session_state.loaded_order_data = {
                                'order_number': str(row.get('НОМЕР_ЗАЯВКИ', "")),
                                'client_phone': str(row.get('ТЕЛЕФОН', "")),
                                'address': str(row.get('АДРЕС', "")),
                                'comment': str(row.get('КОММЕНТАРИЙ', "")),
                                'calculator_items': parse_order_text_to_items(str(row.get('ЗАКАЗ', "")))
                            }


                            delivery_dt_str = str(row.get(DELIVERY_DATE_COLUMN_NAME, "")) 
                            try:
                                dt_obj = datetime.strptime(delivery_dt_str, PARSE_DATETIME_FORMAT)
                                st.session_state.loaded_order_data['delivery_date'] = dt_obj.date()
                                st.session_state.loaded_order_data['delivery_time'] = dt_obj.time()
                            except (ValueError, TypeError):
                                st.session_state.loaded_order_data['delivery_date'] = get_default_delivery_date()
                                st.session_state.loaded_order_data['delivery_time'] = get_default_delivery_time()


                            st.session_state.calculator_items = st.session_state.loaded_order_data['calculator_items']


                            st.session_state.form_key += 1 
                            st.success(f"Заявка №{search_number} загружена для редактирования.")
                            st.rerun()
                        else:
                            st.error(f"Заявка с номером {search_number} не найдена")
                    except Exception as e:
                        st.error(f"Ошибка при загрузке заявки: {e}")
                else:
                    st.error("Введите номер заявки")
            st.markdown("---")


        # ====================
        # ОСНОВНАЯ ФОРМА
        # ====================
        st.subheader("Основные Данные Заявки")
        
        form_key = st.session_state.form_key
        
        if st.session_state.app_mode == 'new':
            default_order_number = generate_next_order_number()
            default_client_phone = ""
            default_address = ""
            default_comment = ""
            default_delivery_date = get_default_delivery_date()
            default_delivery_time = get_default_delivery_time()
        else:
            if st.session_state.loaded_order_data:
                default_order_number = st.session_state.loaded_order_data.get('order_number', "")
                default_client_phone = st.session_state.loaded_order_data.get('client_phone', "")
                default_address = st.session_state.loaded_order_data.get('address', "")
                default_comment = st.session_state.loaded_order_data.get('comment', "")
                default_delivery_date = st.session_state.loaded_order_data.get('delivery_date', get_default_delivery_date())
                default_delivery_time = st.session_state.loaded_order_data.get('delivery_time', get_default_delivery_time())
            else:
                default_order_number = ""
                default_client_phone = ""
                default_address = ""
                default_comment = ""
                default_delivery_date = get_default_delivery_date()
                default_delivery_time = get_default_delivery_time()


        # ✅ ИСПРАВЛЕНИЕ: Изменяем соотношение колонок для Номера Заявки и Телефона 
        # (например, 1:3) для расширения поля телефона
        col1, col2 = st.columns([1, 3])
        col3, col4 = st.columns(2)


        with col1:
            if st.session_state.app_mode == 'new':
                order_number = st.text_input(
                    "Номер Заявки",
                    value=default_order_number,
                    key=f'order_number_new_{form_key}'
                )
            else:
                order_number = st.text_input(
                    "Номер Заявки",
                    value=default_order_number,
                    key=f'order_number_edit_{form_key}',
                    disabled=True 
                )
                
        with col2:
            # ✅ ИСПРАВЛЕНИЕ: Используем st.text_area с минимальной высотой для расширения поля ввода телефона
            client_phone = st.text_area(
                "Телефон Клиента (с 7)",
                value=default_client_phone,
                height=30, # Устанавливаем минимальную высоту, чтобы выглядело как однострочный ввод
                key=f'client_phone_{form_key}'
            )


        with col3:
            delivery_date = st.date_input(
                "Дата Доставки",
                value=default_delivery_date,
                min_value=datetime.today().date(),
                key=f'delivery_date_{form_key}',
                format="DD.MM.YYYY"
            )


        with col4:
            delivery_time = st.time_input(
                "Время Доставки (интервал 30 мин)",
                value=default_delivery_time,
                step=TIME_STEP_SECONDS,
                key=f'delivery_time_{form_key}'
            )


        address = st.text_input(
            "Адрес Доставки",
            value=default_address,
            key=f'address_{form_key}'
        )


        comment = st.text_area(
            "Комментарий / Примечание к заказу (общий)",
            value=default_comment,
            height=50,
            key=f'comment_{form_key}'
        )
        
        st.markdown("---")


        # =========================================================
        # КАЛЬКУЛЯТОР ЗАКАЗА
        # =========================================================
        st.subheader("Состав Заказа (Калькулятор)")
        
        current_qty = 1
        current_comment = ""
        
        col_item, col_qty = st.columns([5, 1])
        
        with col_item:
            selected_item = st.selectbox(
                "Выбор позиции",
                price_items,
                disabled=price_df.empty,
                key=f'item_selector_{form_key}'
            )
        
        with col_qty:
            current_qty = st.number_input(
                "Кол-во",
                min_value=1,
                step=1,
                value=1,
                key=f'item_qty_{form_key}'
            )
        
        col_comment, col_add = st.columns([5, 1])
        
        with col_comment:
            current_comment = st.text_input(
                "Комментарий к позиции",
                value="",
                key=f'item_comment_{form_key}'
            )
            
        with col_add:
            st.markdown(" ")
            if st.button(
                "➕ Добавить",
                use_container_width=True,
                disabled=selected_item == price_items[0],
                key=f'add_item_button_{form_key}'
            ):
                if selected_item != price_items[0]:
                    price_row = price_df[price_df['НАИМЕНОВАНИЕ'] == selected_item]
                    if not price_row.empty:
                        price = float(price_row.iloc[0]['ЦЕНА'])
                        
                        st.session_state.calculator_items.append({
                            'НАИМЕНОВАНИЕ': selected_item,
                            'КОЛИЧЕСТВО': current_qty,
                            'ЦЕНА_ЗА_ЕД': price,
                            'СУММА': price * current_qty,
                            'КОММЕНТАРИЙ_ПОЗИЦИИ': current_comment
                        })
                        st.rerun()


        # Отображение товаров
        total_sum = 0
        if st.session_state.calculator_items:
            df_items = pd.DataFrame(st.session_state.calculator_items)
            total_sum = df_items['СУММА'].sum()
            
            st.dataframe(
                df_items[['НАИМЕНОВАНИЕ', 'КОЛИЧЕСТВО', 'ЦЕНА_ЗА_ЕД', 'КОММЕНТАРИЙ_ПОЗИЦИИ', 'СУММА']],
                column_config={
                    'НАИМЕНОВАНИЕ': 'Товар',
                    'КОЛИЧЕСТВО': 'Кол-во',
                    'ЦЕНА_ЗА_ЕД': st.column_config.NumberColumn("Цена за ед.", format="%.2f РУБ."),
                    'КОММЕНТАРИЙ_ПОЗИЦИИ': 'Комментарий',
                    'СУММА': st.column_config.NumberColumn("Сумма", format="%.2f РУБ."),
                },
                hide_index=True,
                use_container_width=True
            )


            # Удаление позиций
            st.markdown("##### Удаление позиций:")
            for i in range(len(st.session_state.calculator_items) - 1, -1, -1):
                item = st.session_state.calculator_items[i]
                col_name, col_comment_text, col_sum, col_del = st.columns([4, 2, 1.5, 0.5])
                
                with col_name:
                    st.write(f"**{item['НАИМЕНОВАНИЕ']}** ({item['КОЛИЧЕСТВО']} шт.)")
                with col_comment_text:
                    if item['КОММЕНТАРИЙ_ПОЗИЦИИ']:
                        st.markdown(f"*{item['КОММЕНТАРИЙ_ПОЗИЦИИ']}*")
                    else:
                        st.write("-")
                with col_sum:
                    st.write(f"**{item['СУММА']:,.2f} РУБ.**")
                with col_del:
                    if st.button("❌", key=f"del_{i}_{form_key}"):
                        st.session_state.calculator_items.pop(i)
                        st.rerun()


            st.markdown(f"### 💰 **ИТОГО: {total_sum:,.2f} РУБ.**")
        else:
            st.info("В заказе пока нет позиций. Добавьте товар.")


        st.markdown("---")
        
        # =========================================================
        # СОХРАНЕНИЕ ДАННЫХ
        # =========================================================
        st.subheader("Завершение Заявки")


        # Приводим значение text_area к строке и удаляем лишние пробелы/переносы
        phone_input = st.session_state.get(f'client_phone_{form_key}', default_client_phone).strip().replace('\n', '')
        valid_phone = is_valid_phone(phone_input)
        
        is_ready_to_send = (
            order_number and
            valid_phone and
            address and
            st.session_state.calculator_items
        )


        if not is_ready_to_send:
            missing_fields = []
            if not order_number: missing_fields.append("Номер Заявки")
            if not phone_input: missing_fields.append("Телефон Клиента")
            elif not valid_phone: missing_fields.append("Телефон (неверный формат 7XXXXXXXXXX)")
            if not address: missing_fields.append("Адрес Доставки")
            if not st.session_state.calculator_items: missing_fields.append("Состав Заказа")
            if missing_fields:
                st.error(f"❌ Заявка не готова к сохранению! Необходимо заполнить: {', '.join(missing_fields)}")


        def format_order_item(item):
            # Формат сохранения: Наименование - Кол-во шт. (по Цена РУБ.) | Комментарий
            base = f"{item['НАИМЕНОВАНИЕ']} - {item['КОЛИЧЕСТВО']} шт. (по {item['ЦЕНА_ЗА_ЕД']:,.2f} РУБ.)"
            if item.get('КОММЕНТАРИЙ_ПОЗИЦИИ'):
                base += f" | {item['КОММЕНТАРИЙ_ПОЗИЦИИ']}"
            return base
            
        order_details = "\n".join([format_order_item(item) for item in st.session_state.calculator_items])


        entry_datetime = datetime.now()
        entry_datetime_str = entry_datetime.strftime(SHEET_DATETIME_FORMAT)
        
        delivery_datetime = datetime.combine(delivery_date, delivery_time)
        delivery_datetime_str = delivery_datetime.strftime(SHEET_DATETIME_FORMAT)
        
        data_to_save = [
            entry_datetime_str, # 0. ДАТА_ВВОДА
            order_number,       # 1. НОМЕР_ЗАЯВКИ
            valid_phone,        # 2. ТЕЛЕФОН
            address,            # 3. АДРЕС
            delivery_datetime_str, # 4. ДАТА ДОСТАВКИ
            comment,            # 5. КОММЕНТАРИЙ (Общий к заказу)
            order_details,      # 6. ЗАКАЗ (Включает комментарии позиций)
            float(total_sum) if not math.isnan(total_sum) else 0.0 # 7. СУММА
        ]
        
        col_save1, col_save2 = st.columns(2)
        with col_save1:
            if st.session_state.app_mode == 'new':
                if st.button("💾 Сохранить Новую Заявку", disabled=not is_ready_to_send, type="primary", use_container_width=True, key=f'save_new_order_{form_key}'):
                    if save_order_data(data_to_save, orders_ws):
                        st.session_state.last_success_message = f"🎉 Заявка №{order_number} успешно сохранена!"
                        st.session_state.form_reset_trigger = True
            else:
                if st.button("💾 Перезаписать Заявку", disabled=not is_ready_to_send, type="primary", use_container_width=True, key=f'update_order_{form_key}'):
                    if update_order_data(order_number, data_to_save, orders_ws):
                        st.session_state.last_success_message = f"🎉 Заявка №{order_number} успешно перезаписана!"
                        st.session_state.loaded_order_data = None
                        st.rerun()


        with col_save2:
            if st.button("🔄 Очистить форму", use_container_width=True, key=f'clear_form_{form_key}'):
                st.session_state.form_reset_trigger = True
                st.rerun()


        if is_ready_to_send:
            whatsapp_data = {
                'НОМЕР_ЗАЯВКИ': order_number,
                'ТЕЛЕФОН': valid_phone,
                'АДРЕС': address,
                DELIVERY_DATE_COLUMN_NAME: delivery_datetime.strftime('%d.%m.%Y %H:%M'), 
                'КОММЕНТАРИЙ': comment,
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
        
    # =========================================================
    # ВКЛАДКА 2: СПИСОК ЗАЯВОК (ИСПРАВЛЕННАЯ ВЕРСИЯ)
    # =========================================================
    with tab_order_list:
        st.header("📋 Просмотр и Поиск Заявок")


        all_orders_df = load_all_orders()


        if all_orders_df.empty:
            st.warning("Лист 'ЗАЯВКИ' пуст или произошла ошибка при загрузке.")
        else:
            df_display = all_orders_df.copy()


            df_display['НОМЕР_ЗАЯВКИ'] = df_display['НОМЕР_ЗАЯВКИ'].astype(str)
            df_display['СУММА'] = pd.to_numeric(df_display['СУММА'], errors='coerce').fillna(0)


            df_display['ДАТА_ВВОДА_ОТОБРАЖЕНИЕ'] = df_display['ДАТА_ВВОДА'].apply(format_datetime_for_display)
            
            df_display['ДАТА_ДОСТАВКИ_ОТОБРАЖЕНИЕ'] = df_display[DELIVERY_DATE_COLUMN_NAME].apply(format_datetime_for_display)


            try:
                df_display['ДАТА_ДОСТАВКИ_DT'] = pd.to_datetime(df_display[DELIVERY_DATE_COLUMN_NAME], format=PARSE_DATETIME_FORMAT, errors='coerce')
            except:
                df_display['ДАТА_ДОСТАВКИ_DT'] = pd.to_datetime(df_display[DELIVERY_DATE_COLUMN_NAME], errors='coerce')
            
            # Заменяем \n на HTML-тег <br> для переноса строк в ячейке ЗАКАЗ
            df_display['ЗАКАЗ_HTML'] = df_display['ЗАКАЗ'].str.replace('\n', '<br>', regex=False)




            # 2. Поиск и фильтрация
            st.subheader("Поиск")
            search_term = st.text_input("🔍 Введите № заявки, телефон или часть адреса:", key='order_search_list')


            if search_term:
                search_lower = search_term.lower()
                df_display = df_display[
                    df_display['НОМЕР_ЗАЯВКИ'].str.contains(search_lower, na=False) |
                    df_display['ТЕЛЕФОН'].astype(str).str.contains(search_lower, na=False) |
                    df_display['АДРЕС'].astype(str).str.contains(search_lower, case=False, na=False)
                ]
                st.info(f"Отображается заявок: **{len(df_display)}**")


            # 3. Визуально красивый вывод с исправленными датами
            display_columns = [
                'ДАТА_ВВОДА_ОТОБРАЖЕНИЕ', 'НОМЕР_ЗАЯВКИ', 'ТЕЛЕФОН', 'АДРЕС',
                'ДАТА_ДОСТАВКИ_ОТОБРАЖЕНИЕ', 'КОММЕНТАРИЙ', 'ЗАКАЗ_HTML', 'СУММА'
            ]
            
            st.dataframe(
                df_display.sort_values(by='ДАТА_ДОСТАВКИ_DT',
                                       ascending=True)[display_columns],
                column_config={
                    "ДАТА_ВВОДА_ОТОБРАЖЕНИЕ": st.column_config.TextColumn("Введено", width="small"),
                    "НОМЕР_ЗАЯВКИ": st.column_config.TextColumn("№ Заявки", width="small"),
                    "ТЕЛЕФОН": st.column_config.TextColumn("📞 Телефон", width="medium"), 
                    "АДРЕС": st.column_config.TextColumn("📍 Адрес", width="large"),
                    "ДАТА_ДОСТАВКИ_ОТОБРАЖЕНИЕ": st.column_config.TextColumn("️🚚 Доставка", width="medium"),
                    "КОММЕНТАРИЙ": st.column_config.TextColumn("📝 Общий комм.", width="medium"),
                    "ЗАКАЗ_HTML": st.column_config.Column("🛒 Состав Заказа", width="large", is_html=True), 
                    "СУММА": st.column_config.NumberColumn("💰 Сумма", format="%.2f РУБ.", width="small")
                },
                hide_index=True,
                use_container_width=True,
                height=600
            )




if __name__ == "__main__":
    main()