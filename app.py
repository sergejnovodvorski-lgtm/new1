import streamlit as st
import gspread
import pandas as pd
import re
from datetime import datetime, timedelta
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


MANAGER_WHATSAPP_PHONE = "79000000000"


st.set_page_config(
    page_title="CRM: Ввод Новой Заявки",
    layout="wide",
    initial_sidebar_state="expanded"
)


# =========================================================
# БАЗОВЫЕ ФУНКЦИИ
# =========================================================


@st.cache_resource(ttl=3600)
def get_gsheet_client():
    if "gcp_service_account" not in st.secrets:
        st.error("Секрет 'gcp_service_account' не найден.")
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
        # Проверяем заголовки
        current_headers = worksheet.row_values(1)
        if current_headers != EXPECTED_HEADERS:
            worksheet.update('A1', [EXPECTED_HEADERS])
        return worksheet
    except Exception as e:
        st.error(f"Ошибка доступа к листу: {e}")
        return None


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
            st.error("В прайсе отсутствуют обязательные столбцы")
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


# =========================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# =========================================================


def reset_quantity():
    """Сбрасывает значение поля ввода количества в 1 после добавления товара."""
    # Эту операцию разрешено выполнять только в on_click/callback
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


def save_order_data(data_row: List[Any], orders_ws) -> bool:
    """Сохраняет новую заявку"""
    if not orders_ws:
        st.error("Не удалось подключиться к Google Sheets")
        return False
    
    try:
        orders_ws.append_row(data_row)
        return True
    except Exception as e:
        st.error(f"Ошибка сохранения заявки: {e}")
        return False


def update_order_data(order_number: str, data_row: List[Any], orders_ws) -> bool:
    """
    Обновляет существующую заявку, находя точный индекс строки в Gspread
    (чтобы избежать ошибок из-за пустых строк).
    """
    if not orders_ws:
        st.error("Не удалось подключиться к Google Sheets")
        return False
    
    try:
        # Получаем значения столбца 'НОМЕР_ЗАЯВКИ' (B, индекс 2)
        col_values = orders_ws.col_values(2) 
        
        # Находим строку (индекс) последней заявки с этим номером,
        # ища с конца списка, чтобы гарантировать последнюю версию заявки.
        target_gspread_row_index = -1
        for i in range(len(col_values) - 1, 0, -1):
            if str(col_values[i]) == order_number:
                # Индекс в col_values на 1 меньше номера строки.
                target_gspread_row_index = i + 1 
                break
        
        if target_gspread_row_index == -1:
            st.error(f"Заявка с номером {order_number} не найдена в таблице.")
            return False
        
        # Обновляем диапазон от A до H в найденной строке
        orders_ws.update(f'A{target_gspread_row_index}:H{target_gspread_row_index}', [data_row])
        return True
        
    except Exception as e:
        st.error(f"Ошибка обновления заявки: {e}")
        return False


def generate_whatsapp_url(target_phone: str, order_data: Dict[str, str], total_sum: float) -> str:
    text = f"Здравствуйте! Пожалуйста, проверьте детали вашего заказа:\n\n"
    text += f"📋 *Номер Заявки:* {order_data['НОМЕР_ЗАЯВКИ']}\n"
    text += f"📞 *Телефон:* {order_data['ТЕЛЕФОН']}\n"
    text += f"📍 *Адрес:* {order_data['АДРЕС']}\n"
    text += f"🗓️ *Дата Доставки:* {order_data['ДАТА_ДОСТАВКИ']}\n"
    
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
    # Инициализация состояния (Сделано надежно)
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
    if 'new_item_qty' not in st.session_state:
        st.session_state.new_item_qty = 1
    # Инициализация ключа для виджета number_input
    if 'new_item_qty_input' not in st.session_state:
        st.session_state.new_item_qty_input = 1
    if 'last_success_message' not in st.session_state:
        st.session_state.last_success_message = None
    
    # Загрузка данных
    price_df = load_price_list()
    orders_ws = get_orders_worksheet()
    price_items = ["--- Выберите позицию ---"] + price_df['НАИМЕНОВАНИЕ'].tolist() if not price_df.empty else ["--- Прайс не загружен ---"]


    st.title("Ввод Новой Заявки CRM 📝")


    # Обработка успешного сообщения
    if st.session_state.last_success_message:
        st.success(st.session_state.last_success_message)
        st.session_state.last_success_message = None


    # =========================================================
    # ВЫБОР РЕЖИМА РАБОТЫ
    # =========================================================


    st.subheader("Выбор Режима Работы")


    mode = st.radio(
        "Выберите действие:",
        ['Новая заявка', 'Редактировать существующую'],
        horizontal=True,
        key='mode_selector'
    )


    if mode == 'Новая заявка' and st.session_state.app_mode != 'new':
        st.session_state.app_mode = 'new'
        st.session_state.k_order_number = ""
        st.session_state.k_client_phone = ""
        st.session_state.k_address = ""
        st.session_state.k_comment = ""
        st.session_state.k_delivery_date = get_default_delivery_date()
        st.session_state.calculator_items = []
        st.rerun()
    elif mode == 'Редактировать существующую' and st.session_state.app_mode != 'edit':
        st.session_state.app_mode = 'edit'
        st.session_state.k_order_number = ""
        st.session_state.k_client_phone = ""
        st.session_state.k_address = ""
        st.session_state.k_comment = ""
        st.session_state.k_delivery_date = get_default_delivery_date()
        st.session_state.calculator_items = []
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
                    data = orders_ws.get_all_records()
                    df = pd.DataFrame(data)
                    target_rows = df[df['НОМЕР_ЗАЯВКИ'].astype(str) == search_number]
                    
                    if not target_rows.empty:
                        # Берем последнюю запись
                        row = target_rows.iloc[-1].to_dict()
                        
                        # --- ОБНОВЛЕНИЕ ПЕРЕМЕННЫХ СОСТОЯНИЯ ---
                        st.session_state.k_order_number = str(row.get('НОМЕР_ЗАЯВКИ', ''))
                        st.session_state.k_client_phone = str(row.get('ТЕЛЕФОН', ''))
                        st.session_state.k_address = str(row.get('АДРЕС', ''))
                        st.session_state.k_comment = str(row.get('КОММЕНТАРИЙ', ''))
                        
                        # Дата доставки
                        delivery_date_str = str(row.get('ДАТА_ДОСТАВКИ', ''))
                        try:
                            date_obj = datetime.strptime(delivery_date_str, '%Y-%m-%d').date()
                            st.session_state.k_delivery_date = date_obj
                        except (ValueError, TypeError):
                            st.session_state.k_delivery_date = get_default_delivery_date()
                        
                        # Состав заказа
                        order_text = str(row.get('ЗАКАЗ', ''))
                        st.session_state.calculator_items = parse_order_text_to_items(order_text)
                        
                        st.success(f"✅ Заявка №{search_number} загружена для редактирования. Обновите данные и нажмите 'Перезаписать'.")
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


    with col1:
        if st.session_state.app_mode == 'new':
            # Логика автогенерации номера для новой заявки
            if not st.session_state.k_order_number or st.session_state.k_order_number == "":
                try:
                    if orders_ws:
                        data = orders_ws.get_all_records()
                        df = pd.DataFrame(data)
                        if not df.empty and 'НОМЕР_ЗАЯВКИ' in df.columns:
                            order_numbers = [int(n) for n in df['НОМЕР_ЗАЯВКИ'] if str(n).isdigit()]
                            next_number = max(order_numbers) + 1 if order_numbers else 1001
                            st.session_state.k_order_number = str(next_number)
                        else:
                            st.session_state.k_order_number = "1001"
                    else:
                        st.session_state.k_order_number = "1001"
                except:
                    st.session_state.k_order_number = "1001"
            
            st.text_input("Номер Заявки", value=st.session_state.k_order_number, disabled=True, key='display_order_number')
        else:
            st.text_input("Номер Заявки", value=st.session_state.k_order_number, disabled=True, key='display_order_number_edit')


        st.text_input(
            "Телефон Клиента (с 7)",
            value=st.session_state.k_client_phone,
            key='k_client_phone' 
        )


    with col2:
        st.date_input(
            "Дата Доставки",
            value=st.session_state.k_delivery_date,
            min_value=datetime.today().date(),
            key='k_delivery_date' 
        )
        
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
        # Используем session_state.new_item_qty_input для управления значением
        quantity = st.number_input(
            "Кол-во", 
            min_value=1, 
            step=1, 
            value=st.session_state.new_item_qty_input, 
            key='new_item_qty_input'
        )


    with col_add:
        st.markdown(" ")
        # ИСПРАВЛЕНО: on_click для сброса количества
        if st.button(
            "➕ Добавить", 
            use_container_width=True, 
            disabled=selected_item == price_items[0],
            on_click=reset_quantity # <--- Сброс количества
        ):
            if selected_item != price_items[0]:
                price_row = price_df[price_df['НАИМЕНОВАНИЕ'] == selected_item]
                if not price_row.empty:
                    price = float(price_row.iloc[0]['ЦЕНА'])
                    st.session_state.calculator_items.append({
                        'НАИМЕНОВАНИЕ': selected_item,
                        # Берем актуальное значение из ключа виджета
                        'КОЛИЧЕСТВО': st.session_state.new_item_qty_input, 
                        'ЦЕНА_ЗА_ЕД': price,
                        'СУММА': price * st.session_state.new_item_qty_input
                    })
                    # st.rerun() вызывается автоматически после on_click и логики кнопки.
                    st.rerun() # Оставляем rerund для обновления списка товаров


    # Отображение товаров
    total_sum = 0
    if st.session_state.calculator_items:
        df_items = pd.DataFrame(st.session_state.calculator_items)
        total_sum = df_items['СУММА'].sum()
        
        st.dataframe(
            df_items[['НАИМЕНОВАНИЕ', 'КОЛИЧЕСТВО', 'ЦЕНА_ЗА_ЕД', 'СУММА']],
            column_config={
                'НАИМЕНОВАНИЕ': 'Товар',
                'КОЛИЧЕЕСТВО': 'Кол-во',
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


    # Проверка готовности к сохранению (Используем актуальные значения из st.session_state)
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


    data_to_save = [
        datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        st.session_state.k_order_number,
        valid_phone,
        st.session_state.k_address,
        st.session_state.k_delivery_date.strftime('%Y-%m-%d'),
        st.session_state.k_comment,
        order_details,
        float(total_sum) if not math.isnan(total_sum) else 0.0
    ]


    # Кнопка сохранения
    if st.session_state.app_mode == 'new':
        if st.button("💾 Сохранить Новую Заявку", disabled=not is_ready_to_send, type="primary", use_container_width=True):
            if save_order_data(data_to_save, orders_ws):
                st.session_state.last_success_message = f"🎉 Заявка №{st.session_state.k_order_number} успешно сохранена!"
                # Сброс формы
                st.session_state.k_order_number = ""
                st.session_state.k_client_phone = ""
                st.session_state.k_address = ""
                st.session_state.k_comment = ""
                st.session_state.k_delivery_date = get_default_delivery_date()
                st.session_state.calculator_items = []
                st.rerun()
    else:
        if st.button("💾 Перезаписать Заявку", disabled=not is_ready_to_send, type="primary", use_container_width=True):
            if update_order_data(st.session_state.k_order_number, data_to_save, orders_ws):
                st.session_state.last_success_message = f"🎉 Заявка №{st.session_state.k_order_number} успешно перезаписана!"
                st.rerun()


    # Ссылка WhatsApp
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


if __name__ == "__main__":
    main()