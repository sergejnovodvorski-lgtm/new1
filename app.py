import streamlit as st
import gspread
import pandas as pd
import re
from datetime import datetime, timedelta, time
import urllib.parse
from typing import List, Dict, Any
import math


# =========================================================
# КОНСТАНТЫ И НАСТРОЙКИ
# =========================================================


SPREADSHEET_NAME = "Start"
WORKSHEET_NAME_ORDERS = "ЗАЯВКИ"
WORKSHEET_NAME_PRICE = "ПРАЙС"


EXPECTED_HEADERS = [
    "ДАТА_ВВОДА", "НОМЕР_ЗАЯВКИ", "ТЕЛЕФОН", "АДРЕС", "ДАТА_ДОСТАВКИ", 
    "КОММЕНТАРИЙ", "ЗАКАЗ", "СУММА"
]


# Индекс столбца для сортировки/вставки: ДАТА_ДОСТАВКИ (E)
DELIVERY_DATE_COLUMN_INDEX = 5 


# ЗАМЕНИТЕ ЭТОТ НОМЕР НА НОМЕР МЕНЕДЖЕРА
MANAGER_WHATSAPP_PHONE = "79000000000" 


# Интервал 10 минут в секундах
TIME_STEP_SECONDS = 600 


# --- ФОРМАТЫ ДАТЫ ---
# Формат для сохранения в Google Sheets (ДД.ММ.ГГГГ ЧЧ:ММ:СС)
SHEET_DATETIME_FORMAT = '%d.%m.%Y %H:%M:%S'
# Формат для отображения в Streamlit (ДД.ММ.ГГГГ ЧЧ:ММ)
DISPLAY_DATETIME_FORMAT = 'DD.MM.YYYY HH:mm'
# Формат для парсинга и сортировки
PARSE_DATETIME_FORMAT = '%d.%m.%Y %H:%M:%S'




st.set_page_config(
    page_title="CRM: Ввод Новой Заявки",
    layout="wide",
    initial_sidebar_state="expanded"
)


# =========================================================
# БАЗОВЫЕ ФУНКЦИИ (Работа с данными и Google Sheets)
# =========================================================


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
            worksheet.update('A1', [EXPECTED_HEADERS]) 
        return worksheet
    except Exception as e:
        st.error(f"Ошибка доступа к листу '{WORKSHEET_NAME_ORDERS}': {e}")
        return None


@st.cache_data(ttl="1h")
def load_all_orders():
    """Загружает все заявки с листа 'ЗАЯВКИ'."""
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


# =========================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ (Логика приложения)
# =========================================================


def reset_form_fields():
    st.session_state.k_order_number = ""
    st.session_state.k_client_phone = ""
    st.session_state.k_address = ""
    st.session_state.k_comment = ""
    st.session_state.k_delivery_date = get_default_delivery_date()
    st.session_state.k_delivery_time = get_default_delivery_time()
    st.session_state.calculator_items = []
    
    if 'new_item_qty_input' in st.session_state:
        st.session_state.new_item_qty_input = 1


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


def get_insert_index(new_delivery_date_str: str, orders_ws) -> int:
    """
    Находит индекс строки (начиная с 2), перед которой должна быть вставлена новая заявка,
    чтобы сохранить хронологический порядок по колонке ДАТА_ДОСТАВКИ.
    """
    if not orders_ws:
        return 2


    try:
        # Загружаем колонку ДАТА_ДОСТАВКИ, начиная со второй строки (после заголовков)
        data_col = orders_ws.col_values(DELIVERY_DATE_COLUMN_INDEX)[1:] 
    except Exception:
        # Если не удалось получить данные, вставляем сразу после заголовков (индекс 2)
        return 2 


    if not data_col:
        return 2
    
    try:
        # Дата доставки новой заявки
        new_date = datetime.strptime(new_delivery_date_str, PARSE_DATETIME_FORMAT)
    except ValueError:
        # Если формат даты новой заявки неверный, вставляем в начало (индекс 2)
        return 2


    # Ищем, где должна быть вставлена новая заявка
    # Итерируемся по существующим датам, предполагая, что они отсортированы
    for i, date_str in enumerate(data_col):
        try:
            # Парсим существующую дату доставки
            existing_date = datetime.strptime(date_str, PARSE_DATETIME_FORMAT)
            
            # Если новая дата доставки РАНЬШЕ или равна существующей,
            # значит, вставлять нужно ПЕРЕД этой существующей строкой.
            # (i + 2): i - индекс в списке data_col (начинается с 0), +1 за пропускание заголовка, +1 за преобразование в gspread-индекс.
            if new_date <= existing_date:
                return i + 2
        except ValueError:
            # Если формат существующей даты неверный, пропускаем эту строку
            continue
            
    # Если новая дата доставки ПОЗДНЕЕ всех существующих, вставляем в самый конец (+2 за заголовок)
    return len(data_col) + 2




def save_order_data(data_row: List[Any], orders_ws) -> bool:
    """
    Сохраняет новую заявку, вставляя ее в хронологическом порядке по ДАТЕ ДОСТАВКИ.
    """
    if not orders_ws:
        return False
    
    try:
        # Дата доставки находится в 5-м элементе data_row (индекс 4)
        new_delivery_date_str = data_row[4]
        
        # 1. Находим индекс строки для вставки по ДАТЕ ДОСТАВКИ
        insert_index = get_insert_index(new_delivery_date_str, orders_ws)
        
        # 2. Вставляем строку
        orders_ws.insert_row(data_row, index=insert_index)
        
        # Принудительно очищаем кэш заявок
        load_all_orders.clear() 
        return True
    except Exception as e:
        st.error(f"Ошибка сохранения заявки: {e}")
        return False


def update_order_data(order_number: str, data_row: List[Any], orders_ws) -> bool:
    """Обновляет существующую заявку, перезаписывая ее."""
    if not orders_ws:
        return False
    
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
        
        # Обновляем диапазон в найденной строке
        orders_ws.update(f'A{target_gspread_row_index}:H{target_gspread_row_index}', [data_row])
        load_all_orders.clear() 
        return True
        
    except Exception as e:
        st.error(f"Ошибка обновления заявки: {e}")
        return False


def generate_whatsapp_url(target_phone: str, order_data: Dict[str, str], total_sum: float) -> str:
    text = f"Здравствуйте! Пожалуйста, проверьте детали вашего заказа:\n\n"
    text += f"📋 *Номер Заявки:* {order_data['НОМЕР_ЗАЯВКИ']}\n"
    text += f"📞 *Телефон:* {order_data['ТЕЛЕФОН']}\n"
    text += f"📍 *Адрес:* {order_data['АДРЕС']}\n"
    text += f"🗓️ *Дата и Время Доставки:* {order_data['ДАТА_ДОСТАВКИ']}\n"
    
    if order_data.get('КОММЕНТАРИЙ'):
        text += f"📝 *Комментарий:* {order_data['КОММЕНТАРИЙ']}\n"
    
    text += f"\n🛒 *Состав Заказа:*\n{order_data['ЗАКАЗ']}\n\n"
    text += f"💰 *ИТОГО: {total_sum:,.2f} РУБ.*\n\n"
    text += "Пожалуйста, подтвердите заказ или укажите необходимые изменения."
    
    encoded_text = urllib.parse.quote(text)
    normalized_phone = is_valid_phone(target_phone)
    
    if not normalized_phone:
        target_phone_final = MANAGER_WHATSAPP_PHONE
    else:
        target_phone_final = normalized_phone
        
    return f"https://wa.me/{target_phone_final}?text={encoded_text}"




# =========================================================
# ОСНОВНАЯ ЛОГИКА ПРИЛОЖЕНИЯ
# =========================================================


def main():
    # Инициализация состояния (без изменений)
    if 'app_mode' not in st.session_state:
        st.session_state.app_mode = 'new'
    if 'calculator_items' not in st.session_state:
        st.session_state.calculator_items = []
    if 'k_order_number' not in st.session_state:
        st.session_state.k_order_number = ""
    if 'k_client_phone' not in st.session_state:
        st.session_state.k_client_phone = ""
    if 'k_address' not in st.session_state:
        st.session_state.k_address = ""
    if 'k_comment' not in st.session_state:
        st.session_state.k_comment = ""
    if 'k_delivery_date' not in st.session_state:
        st.session_state.k_delivery_date = get_default_delivery_date()
    if 'k_delivery_time' not in st.session_state:
        st.session_state.k_delivery_time = get_default_delivery_time()
    if 'new_item_qty_input' not in st.session_state:
        st.session_state.new_item_qty_input = 1
    if 'last_success_message' not in st.session_state:
        st.session_state.last_success_message = None
    
    # Загрузка данных
    price_df = load_price_list()
    orders_ws = get_orders_worksheet()
    price_items = ["--- Выберите позицию ---"] + price_df['НАИМЕНОВАНИЕ'].tolist() if not price_df.empty else ["--- Прайс не загружен ---"]


    st.title("CRM: Управление Заявками 📝")


    # Обработка успешного сообщения
    if st.session_state.last_success_message:
        st.success(st.session_state.last_success_message)
        st.session_state.last_success_message = None


    # =========================================================
    # ГЛАВНОЕ РАЗДЕЛЕНИЕ НА ВКЛАДКИ
    # =========================================================
    tab_order_entry, tab_order_list = st.tabs(["🛒 Ввод/Редактирование Заявки", "📋 Список Заявок"])
    
    
    # =========================================================
    # ВКЛАДКА 1: ВВОД/РЕДАКТИРОВАНИЕ ЗАЯВКИ
    # =========================================================
    with tab_order_entry:


        st.subheader("Выбор Режима Работы")


        mode = st.radio(
            "Выберите действие:",
            ['Новая заявка', 'Редактировать существующую'],
            horizontal=True,
            key='mode_selector'
        )


        # Логика переключения режимов
        if mode == 'Новая заявка' and st.session_state.app_mode != 'new':
            st.session_state.app_mode = 'new'
            reset_form_fields() 
            st.rerun()
        elif mode == 'Редактировать существующую' and st.session_state.app_mode != 'edit':
            st.session_state.app_mode = 'edit'
            reset_form_fields() 
            st.rerun()


        st.info("➕ **Режим Создания Новой Заявки**" if st.session_state.app_mode == 'new' else "🔄 **Режим Редактирования/Перезаписи**")


        # =========================================================
        # ПОИСК СУЩЕСТВУЮЩЕЙ ЗАЯВКИ
        # =========================================================


        if st.session_state.app_mode == 'edit':
            st.subheader("Поиск заявки для редактирования")
            search_number = st.text_input("Введите номер заявки для поиска:", key='search_input')
            
            if st.button("🔍 Найти и загрузить заявку", use_container_width=True):
                if search_number and orders_ws:
                    try:
                        df = load_all_orders() 
                        target_rows = df[df['НОМЕР_ЗАЯВКИ'].astype(str) == search_number]
                        
                        if not target_rows.empty:
                            row = target_rows.iloc[-1].to_dict()
                            
                            st.session_state.k_order_number = str(row.get('НОМЕР_ЗАЯВКИ', ''))
                            st.session_state.k_client_phone = str(row.get('ТЕЛЕФОН', ''))
                            st.session_state.k_address = str(row.get('АДРЕС', ''))
                            st.session_state.k_comment = str(row.get('КОММЕНТАРИЙ', ''))
                            
                            delivery_dt_str = str(row.get('ДАТА_ДОСТАВКИ', ''))
                            try:
                                # Парсинг ДД.ММ.ГГГГ ЧЧ:ММ:СС
                                dt_obj = datetime.strptime(delivery_dt_str, PARSE_DATETIME_FORMAT)
                                st.session_state.k_delivery_date = dt_obj.date()
                                st.session_state.k_delivery_time = dt_obj.time()
                            except (ValueError, TypeError):
                                st.session_state.k_delivery_date = get_default_delivery_date()
                                st.session_state.k_delivery_time = get_default_delivery_time()
                            
                            order_text = str(row.get('ЗАКАЗ', ''))
                            st.session_state.calculator_items = parse_order_text_to_items(order_text)
                            
                            st.success(f"✅ Заявка №{search_number} загружена для редактирования.")
                            st.rerun()
                        else:
                            st.error(f"❌ Заявка с номером {search_number} не найдена")
                    except Exception as e:
                        st.error(f"Ошибка при загрузке заявки: {e}")
                else:
                    st.error("Введите номер заявки")


            st.markdown("---")


        # =========================================================
        # ОСНОВНАЯ ФОРМА
        # =========================================================


        st.subheader("Основные Данные Заявки")


        col1, col2 = st.columns(2)
        col3, col4 = st.columns(2)


        with col1:
            if st.session_state.app_mode == 'new':
                # Логика автогенерации номера для новой заявки
                if not st.session_state.k_order_number or st.session_state.k_order_number == "":
                    try:
                        df = load_all_orders()
                        if not df.empty and 'НОМЕР_ЗАЯВКИ' in df.columns:
                            order_numbers = [int(n) for n in df['НОМЕР_ЗАЯВКИ'] if str(n).isdigit()]
                            next_number = max(order_numbers) + 1 if order_numbers else 1001
                            st.session_state.k_order_number = str(next_number)
                        else:
                            st.session_state.k_order_number = "1001"
                    except:
                        st.session_state.k_order_number = "1001"
                
                st.text_input("Номер Заявки", value=st.session_state.k_order_number, disabled=True, key='display_order_number')
            else:
                st.text_input("Номер Заявки", value=st.session_state.k_order_number, disabled=True, key='display_order_number_edit')


        with col2:
            st.text_input(
                "Телефон Клиента (с 7)",
                value=st.session_state.k_client_phone,
                key='k_client_phone' 
            )
        
        # --- Поля для даты и времени ---
        with col3:
            st.date_input(
                "Дата Доставки",
                value=st.session_state.k_delivery_date,
                min_value=datetime.today().date(),
                key='k_delivery_date',
                format="DD.MM.YYYY" 
            )
        
        with col4:
            st.time_input(
                "Время Доставки (интервал 10 мин)",
                value=st.session_state.k_delivery_time,
                step=TIME_STEP_SECONDS, 
                key='k_delivery_time'
            )
        
        # --- Поле адреса и комментария ---
        st.text_input(
            "Адрес Доставки",
            value=st.session_state.k_address,
            key='k_address'
        )


        st.text_area(
            "Комментарий / Примечание",
            value=st.session_state.k_comment,
            height=50,
            key='k_comment' 
        )


        st.markdown("---")


        # =========================================================
        # КАЛЬКУЛЯТОР ЗАКАЗА 
        # =========================================================


        st.subheader("Состав Заказа (Калькулятор)")


        col_item, col_qty, col_add = st.columns([4, 1, 1])


        with col_item:
            selected_item = st.selectbox("Выбор позиции", price_items, disabled=price_df.empty)


        with col_qty:
            quantity = st.number_input(
                "Кол-во", 
                min_value=1, 
                step=1, 
                value=st.session_state.new_item_qty_input, 
                key='new_item_qty_input'
            )


        with col_add:
            st.markdown(" ")
            if st.button(
                "➕ Добавить", 
                use_container_width=True, 
                disabled=selected_item == price_items[0]
            ):
                if selected_item != price_items[0]:
                    price_row = price_df[price_df['НАИМЕНОВАНИЕ'] == selected_item]
                    if not price_row.empty:
                        price = float(price_row.iloc[0]['ЦЕНА'])
                        st.session_state.calculator_items.append({
                            'НАИМЕНОВАНИЕ': selected_item,
                            'КОЛИЧЕСТВО': st.session_state.new_item_qty_input, 
                            'ЦЕНА_ЗА_ЕД': price,
                            'СУММА': price * st.session_state.new_item_qty_input
                        })
                        st.rerun()


        # Отображение товаров
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
            
            # Удаление позиций
            st.markdown("##### Удаление позиций:")
            for i in range(len(st.session_state.calculator_items) - 1, -1, -1):
                item = st.session_state.calculator_items[i]
                col_name, col_sum, col_del = st.columns([5, 1.5, 0.5])
                with col_name:
                    st.write(f"**{item['НАИМЕНОВАНИЕ']}** ({item['КОЛИЧЕСТВО']} шт.)")
                with col_sum:
                    st.write(f"**{item['СУММА']:,.2f} РУБ.**")
                with col_del:
                    if st.button("❌", key=f"del_{i}"):
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


        valid_phone = is_valid_phone(st.session_state.k_client_phone)
        is_ready_to_send = (
            st.session_state.k_order_number and 
            valid_phone and 
            st.session_state.k_address and 
            st.session_state.calculator_items
        )


        if not is_ready_to_send:
            missing_fields = []
            if not st.session_state.k_order_number:
                missing_fields.append("Номер Заявки")
            if not st.session_state.k_client_phone:
                missing_fields.append("Телефон Клиента")
            elif not valid_phone:
                missing_fields.append("Телефон (неверный формат 7XXXXXXXXXX)")
            if not st.session_state.k_address:
                missing_fields.append("Адрес Доставки")
            if not st.session_state.calculator_items:
                missing_fields.append("Состав Заказа")
            
            if missing_fields:
                st.error(f"❌ Заявка не готова к сохранению! Необходимо заполнить: {', '.join(missing_fields)}")


        # Подготовка данных
        order_details = "\n".join(
            [f"{item['НАИМЕНОВАНИЕ']} - {item['КОЛИЧЕСТВО']} шт. (по {item['ЦЕНА_ЗА_ЕД']:,.2f} РУБ.)" 
             for item in st.session_state.calculator_items]
        )
        
        # Дата и время создания заявки (столбец A)
        entry_datetime = datetime.now()
        entry_datetime_str = entry_datetime.strftime(SHEET_DATETIME_FORMAT)
        
        # Дата и время доставки (столбец E) - используется для сортировки/вставки
        delivery_datetime = datetime.combine(st.session_state.k_delivery_date, st.session_state.k_delivery_time)
        delivery_datetime_str = delivery_datetime.strftime(SHEET_DATETIME_FORMAT)


        data_to_save = [
            entry_datetime_str, # 0. ДАТА_ВВОДА
            st.session_state.k_order_number, # 1. НОМЕР_ЗАЯВКИ
            valid_phone, # 2. ТЕЛЕФОН
            st.session_state.k_address, # 3. АДРЕС
            delivery_datetime_str, # 4. ДАТА_ДОСТАВКИ (используется для сортировки)
            st.session_state.k_comment, # 5. КОММЕНТАРИЙ
            order_details, # 6. ЗАКАЗ
            float(total_sum) if not math.isnan(total_sum) else 0.0 # 7. СУММА
        ]


        # Кнопка сохранения
        if st.session_state.app_mode == 'new':
            if st.button("💾 Сохранить Новую Заявку", 
                         disabled=not is_ready_to_send, 
                         type="primary", 
                         use_container_width=True,
                         on_click=reset_form_fields): 
                # Используется обновленная функция save_order_data
                if save_order_data(data_to_save, orders_ws):
                    st.session_state.last_success_message = f"🎉 Заявка №{st.session_state.k_order_number} успешно сохранена!"
                    st.rerun() 
        else:
            if st.button("💾 Перезаписать Заявку", disabled=not is_ready_to_send, type="primary", use_container_width=True):
                # Обновление существующей записи
                if update_order_data(st.session_state.k_order_number, data_to_save, orders_ws):
                    st.session_state.last_success_message = f"🎉 Заявка №{st.session_state.k_order_number} успешно перезаписана!"
                    st.rerun()


        # Ссылка WhatsApp
        if is_ready_to_send:
            whatsapp_data = {
                'НОМЕР_ЗАЯВКИ': st.session_state.k_order_number,
                'ТЕЛЕФОН': st.session_state.k_client_phone,
                'АДРЕС': st.session_state.k_address,
                'ДАТА_ДОСТАВКИ': delivery_datetime.strftime('%d.%m.%Y %H:%M'), 
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
            
    # =========================================================
    # ВКЛАДКА 2: СПИСОК ЗАЯВОК
    # =========================================================
    with tab_order_list:
        st.header("📋 Просмотр и Поиск Заявок")
        
        # 1. Загрузка данных
        all_orders_df = load_all_orders()
        
        if all_orders_df.empty:
            st.warning("Лист 'ЗАЯВКИ' пуст или произошла ошибка при загрузке.")
        else:
            df_display = all_orders_df.copy()
            df_display['НОМЕР_ЗАЯВКИ'] = df_display['НОМЕР_ЗАЯВКИ'].astype(str)
            df_display['СУММА'] = pd.to_numeric(df_display['СУММА'], errors='coerce').fillna(0)
            
            # Парсинг даты доставки для корректной сортировки в Streamlit
            df_display['ДАТА_ДОСТАВКИ_DT'] = pd.to_datetime(df_display['ДАТА_ДОСТАВКИ'], format=PARSE_DATETIME_FORMAT, errors='coerce')
            
            # 2. Поиск и фильтрация
            st.subheader("Поиск")
            search_term = st.text_input("🔍 Введите № заявки, телефон или часть адреса:", key='order_search_list')
            
            if search_term:
                search_lower = search_term.lower()
                df_display = df_display[
                    df_display['НОМЕР_ЗАЯВКИ'].str.contains(search_lower) |
                    df_display['ТЕЛЕФОН'].astype(str).str.contains(search_lower) |
                    df_display['АДРЕС'].astype(str).str.contains(search_lower, case=False)
                ]
            
            st.info(f"Отображается заявок: **{len(df_display)}**")
            
            # 3. Визуально красивый вывод
            # Сортируем по дате доставки (самый ранний заказ вверху)
            st.dataframe(
                df_display.sort_values(by='ДАТА_ДОСТАВКИ_DT', ascending=True).drop(columns=['ДАТА_ДОСТАВКИ_DT']),
                column_config={
                    "ДАТА_ВВОДА": st.column_config.DatetimeColumn("Введено", format=DISPLAY_DATETIME_FORMAT),
                    "ДАТА_ДОСТАВКИ": st.column_config.DatetimeColumn("🗓️ Доставка", format=DISPLAY_DATETIME_FORMAT),
                    
                    "НОМЕР_ЗАЯВКИ": "№ Заявки",
                    "ТЕЛЕФОН": st.column_config.Column("📞 Телефон"),
                    "АДРЕС": st.column_config.Column("📍 Адрес", help="Адрес доставки"),
                    "КОММЕНТАРИЙ": "📝 Комментарий",
                    "ЗАКАЗ": st.column_config.Column("🛒 Состав Заказа", help="Детали заказа"),
                    "СУММА": st.column_config.NumberColumn("💰 Сумма", format="%.2f РУБ.", help="Общая сумма заказа"),
                },
                hide_index=True,
                use_container_width=True,
                height=600 
            )


if __name__ == "__main__":
    main()