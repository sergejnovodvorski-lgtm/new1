import streamlit as st
import gspread
import pandas as pd
import re
from datetime import datetime, timedelta
import urllib.parse
import time


# =========================================================
# 1. КОНСТАНТЫ И НАСТРОЙКИ
# =========================================================


SPREADSHEET_NAME = "Start" 
WORKSHEET_NAME_ORDERS = "ЗАЯВКИ"
# УКАЖИТЕ СВОЙ НОМЕР МЕНЕДЖЕРА (используется только для внутренних целей, не для отправки)
MANAGER_WHATSAPP_PHONE = "79000000000" 


st.set_page_config(
    page_title="CRM: Ввод Новой Заявки", 
    layout="wide",
    initial_sidebar_state="expanded"
)


# Инициализация состояния сессии для хранения данных
if 'critical_error' not in st.session_state:
    st.session_state.critical_error = None
if 'calculator_items' not in st.session_state:
    st.session_state.calculator_items = []
if 'k_client_phone' not in st.session_state:
    st.session_state.k_client_phone = ""
if 'k_order_number' not in st.session_state:
    st.session_state.k_order_number = ""
if 'k_delivery_date' not in st.session_state:
    st.session_state.k_delivery_date = datetime.today().date() + timedelta(days=1)
    
# Функция для записи критической ошибки
def set_critical_error(message, error_details=None):
    full_message = f"Критическая ошибка: {message}"
    if error_details:
        full_message += f"\n\nДетали: {error_details}"
    st.session_state.critical_error = full_message


# =========================================================
# 2. ФУНКЦИИ ПОДКЛЮЧЕНИЯ И КЭШИРОВАНИЯ
# =========================================================


@st.cache_resource(ttl=3600)
def get_gsheet_client():
    if "gcp_service_account" not in st.secrets:
        set_critical_error("Секрет 'gcp_service_account' не найден. Убедитесь, что он настроен в secrets.toml.")
        return None 
    try:
        gc = gspread.service_account_from_dict(st.secrets["gcp_service_account"])
        return gc
    except Exception as e:
        set_critical_error("Ошибка аутентификации gspread.", f"Ошибка: {e}")
        return None


@st.cache_data(ttl="1h")
def load_price_list():
    gc = get_gsheet_client()
    if not gc: return pd.DataFrame() 
        
    try:
        sh = gc.open(SPREADSHEET_NAME) 
        worksheet = sh.worksheet("ПРАЙС") 
        data = worksheet.get_all_records()
        df = pd.DataFrame(data)
        if 'ЦЕНА' in df.columns:
            df['ЦЕНА'] = pd.to_numeric(df['ЦЕНА'], errors='coerce')
        st.info(f"✅ Прайс-лист загружен успешно. Обнаружено {len(df)} позиций.")
        return df
    except gspread.exceptions.SpreadsheetNotFound:
        set_critical_error(f"Google Таблица '{SPREADSHEET_NAME}' не найдена.")
    except gspread.exceptions.WorksheetNotFound:
        set_critical_error("Лист 'ПРАЙС' не найден. Убедитесь в правильности названия.")
    except Exception as e:
        set_critical_error("Неизвестная ошибка при загрузке прайса (проверьте заголовки).", f"Ошибка: {e}")
    return pd.DataFrame()


@st.cache_resource
def get_orders_worksheet():
    gc = get_gsheet_client()
    if not gc: return None
    try:
        sh = gc.open(SPREADSHEET_NAME) 
        return sh.worksheet(WORKSHEET_NAME_ORDERS)
    except gspread.exceptions.WorksheetNotFound:
        set_critical_error(f"Лист для заявок '{WORKSHEET_NAME_ORDERS}' не найден.")
        return None
    except Exception as e:
        set_critical_error(f"Ошибка доступа к листу '{WORKSHEET_NAME_ORDERS}'.", f"Ошибка: {e}")
        return None


# Инициализация
price_df = load_price_list() 
orders_ws = get_orders_worksheet()
price_items = ["--- Выберите позицию ---"] + price_df['НАИМЕНОВАНИЕ'].tolist()


# =========================================================
# 3. ФУНКЦИИ ЛОГИКИ (ПАРСИНГ И ЗАПИСЬ)
# =========================================================


def parse_conversation(text):
    """Базовая функция для извлечения данных из текста переписки и обновления st.session_state."""
    
    # 1. Извлечение номера телефона (Поиск по частоте)
    phone_matches = re.findall(r'(?:\+7|8|\b7)?\s*\(?\s*(\d{3})\s*\)?\s*(\d{3})[-\s]*(\d{2})[-\s]*(\d{2})', text)
    if phone_matches:
        phone_counts = {}
        for match in phone_matches:
            normalized_phone = "7" + "".join(match)
            phone_counts[normalized_phone] = phone_counts.get(normalized_phone, 0) + 1
        phone = max(phone_counts.items(), key=lambda item: item[1])[0]
        # ❗ ИСПРАВЛЕНИЕ: Обновляем session_state, чтобы телефон заполнился в форме
        st.session_state['k_client_phone'] = phone 
        st.info(f"✅ Телефон клиента найден: **{phone}**")




    # 2. Извлечение номера заявки
    order_match = re.search(r'(?:заявк[аи]|заказ|счет|№)\s*(\d+)', text, re.IGNORECASE)
    if order_match:
        st.session_state['k_order_number'] = order_match.group(1)
        st.info(f"✅ Номер Заявки найден: {order_match.group(1)}")




    # 3. Извлечение даты доставки
    delivery_date = None
    
    # ПРОВЕРКА ОТНОСИТЕЛЬНЫХ ДАТ
    if re.search(r'завтра', text, re.IGNORECASE):
        delivery_date = datetime.today().date() + timedelta(days=1)
    elif re.search(r'послезавтра', text, re.IGNORECASE):
        delivery_date = datetime.today().date() + timedelta(days=2)
    
    # ПРОВЕРКА КОНКРЕТНЫХ ДАТ (только если относительная дата еще не найдена)
    else:
        date_match = re.search(r'(\d{1,2})[./](\d{1,2})(?:[./](\d{4}))?', text)
        if date_match:
            day, month, year = date_match.groups()
            current_year = datetime.today().year
            year = int(year) if year else current_year
            try:
                delivery_date = datetime(year, int(month), int(day)).date()
            except ValueError:
                pass
    
    if delivery_date:
        # Корректировка даты (если дата в прошлом)
        if delivery_date < datetime.today().date():
             delivery_date = delivery_date.replace(year=delivery_date.year + 1)
             st.warning("⚠️ Обнаруженная дата была в прошлом. Год скорректирован на следующий.")
             
        st.session_state['k_delivery_date'] = delivery_date
        st.info(f"✅ Дата Доставки найдена: **{delivery_date.strftime('%d.%m.%Y')}**")




def save_data_to_gsheets(data_row):
    """Добавляет строку данных на лист ЗАЯВКИ."""
    if orders_ws is None:
        st.error("Не удалось подключиться к листу для записи данных.")
        return False
    try:
        orders_ws.append_row(data_row)
        return True
    except Exception as e:
        st.error(f"Ошибка записи в Google Sheets: {e}")
        return False


# =========================================================
# 4. ФУНКЦИИ КАЛЬКУЛЯТОРА И ИНТЕРФЕЙСА
# =========================================================


def add_item():
    """Добавляет выбранный товар в список в session_state."""
    selected_name = st.session_state['new_item_select']
    quantity = st.session_state['new_item_qty']
    
    if selected_name != "--- Выберите позицию ---" and quantity > 0:
        price_row = price_df[price_df['НАИМЕНОВАНИЕ'] == selected_name]
        
        if price_row.empty:
             st.error(f"Ошибка: позиция '{selected_name}' не найдена в прайс-листе.")
             return


        price = price_row.iloc[0]['ЦЕНА']
        
        st.session_state.calculator_items.append({
            'НАИМЕНОВАНИЕ': selected_name,
            'КОЛИЧЕСТВО': quantity,
            'ЦЕНА_ЗА_ЕД': price,
            'СУММА': price * quantity
        })




def remove_item(index):
    """Удаляет позицию из списка по индексу."""
    if 0 <= index < len(st.session_state.calculator_items):
        st.session_state.calculator_items.pop(index)
    st.rerun()




def generate_whatsapp_url(target_phone, order_data, total_sum):
    """Генерирует ссылку на WhatsApp с предзаполненным текстом."""
    # Обратите внимание: target_phone теперь - это номер клиента
    text = f"✅ НОВАЯ ЗАЯВКА (CRM)\n"
    text += f"📅 Дата Ввода: {order_data['ДАТА_ВВОДА']}\n"
    text += f"🆔 Номер Заявки: {order_data['НОМЕР_ЗАЯВКИ']}\n"
    text += f"📞 Телефон: {order_data['ТЕЛЕФОН']}\n"
    text += f"📍 Адрес: {order_data['АДРЕС']}\n"
    text += f"🗓️ Дата Доставки: {order_data['ДАТА_ДОСТАВКИ']}\n\n"
    text += f"🛒 Состав Заказа:\n{order_data['ЗАКАЗ']}\n"
    text += f"💰 *ИТОГО: {total_sum:,.2f} РУБ.*\n"
    
    # Кодирование текста для URL
    encoded_text = urllib.parse.quote(text)
    # ❗ ИЗМЕНЕНИЕ: Отправляем на target_phone (номер клиента)
    return f"https://wa.me/{target_phone}?text={encoded_text}"




def display_whatsapp_notification(total_sum, order_items_text, form_data):
    """Генерирует и отображает кнопку WhatsApp, не сохраняя данные в GS."""
    
    # Телефон клиента, на который будет отправлено сообщение
    client_phone_for_wa = form_data['client_phone']
    
    if not client_phone_for_wa:
        st.error("Нельзя отправить уведомление: не указан Телефон клиента.")
        return


    whatsapp_data = {
        'ДАТА_ВВОДА': datetime.now().strftime("%d.%m.%Y %H:%M"),
        'НОМЕР_ЗАЯВКИ': form_data['order_number'],
        'ТЕЛЕФОН': client_phone_for_wa,
        'АДРЕС': form_data['client_address'],
        'ДАТА_ДОСТАВКИ': form_data['delivery_date'].strftime("%d.%m.%Y"),
        'ЗАКАЗ': order_items_text,
    }
    
    # ❗ ИЗМЕНЕНИЕ: Передаем номер клиента в функцию генерации URL
    whatsapp_link = generate_whatsapp_url(client_phone_for_wa, whatsapp_data, total_sum)
    
    st.success("Сообщение для согласования готово!")
    st.markdown(f"**Нажмите, чтобы отправить заказ клиенту ({client_phone_for_wa}):**")
    st.link_button("📲 ОТПРАВИТЬ В WHATSAPP", whatsapp_link, type="primary")




def save_order_to_gsheets(total_sum, order_items_text, form_data):
    """Сохраняет данные в Google Sheets и очищает состояние, не отправляя уведомление."""
    
    # Формируем строку для Google Sheets (согласно колонкам листа ЗАЯВКИ)
    data_row = [
        datetime.now().strftime("%d.%m.%Y %H:%M"), # ДАТА_ВВОДА
        form_data['order_number'],                 # НОМЕР_ЗАЯВКИ
        "",                                        # КЛИЕНТ (пусто)
        form_data['client_phone'],                 # ТЕЛЕФОН
        form_data['client_address'],               # АДРЕС
        form_data['delivery_date'].strftime("%d.%m.%Y"), # ДАТА_ДОСТАВКИ
        order_items_text,                          # ЗАКАЗ (список товаров)
        total_sum,                                 # СУММА
        "Новая"                                    # СТАТУС
    ]
    
    if save_data_to_gsheets(data_row):
        st.success("🎉 Заявка успешно сохранена в Google Sheets и отправлена в CRM!")
        
        # Очистка формы и состояния
        st.session_state.calculator_items = []
        st.session_state.k_client_phone = ""
        st.session_state.k_order_number = ""
        st.session_state.k_delivery_date = datetime.today().date() + timedelta(days=1)
        time.sleep(1)
        st.rerun() 




# =========================================================
# 5. ОСНОВНОЕ ТЕЛО ПРИЛОЖЕНИЯ
# =========================================================


# Проверка критических ошибок
if st.session_state.critical_error:
    st.error("🚨 КРИТИЧЕСКАЯ ОШИБКА ИНИЦИАЛИЗАЦИИ")
    st.markdown(f"**Приложение не может работать из-за следующей проблемы:**")
    st.code(st.session_state.critical_error, language='markdown')


else:
    st.title("CRM: Ввод Новой Заявки")
    
    # ----------------------------------------------------
    # 1. СЕКЦИЯ ПАРСИНГА
    # ----------------------------------------------------
    st.header("1. Автозаполнение по переписке")
    conversation_text = st.text_area(
        "Вставьте текст переписки/заказа для автоматического извлечения данных:", 
        height=150,
        placeholder="Пример: 'Мне нужен заказ №123, привезите завтра на адрес Москва, ул. Ленина, 55. Мой номер 79011234567'"
    )
    if st.button("🔍 ПАРСИТЬ ТЕКСТ", type="secondary"):
        parse_conversation(conversation_text)
    
    st.divider()


    # ----------------------------------------------------
    # 2. ФОРМА ВВОДА ОСНОВНЫХ ДАННЫХ ЗАЯВКИ
    # ----------------------------------------------------
    
    st.header("2. Данные Клиента и Доставки")


    # Рассчитываем итоговую сумму и текст заказа до формы, 
    # чтобы использовать их для отображения и валидации
    total_sum = sum(item['СУММА'] for item in st.session_state.calculator_items)
    order_items_list = [f"{i['НАИМЕНОВАНИЕ']} x {i['КОЛИЧЕСТВО']} ({i['СУММА']:,.2f} руб.)" for i in st.session_state.calculator_items]
    order_items_text = "\n".join(order_items_list)


    with st.form("order_form", clear_on_submit=False):
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.subheader("Контакты")
            client_phone = st.text_input(
                "Телефон", 
                # ❗ ИСПРАВЛЕНИЕ: Значение берется из session_state, который был обновлен парсером
                value=st.session_state.k_client_phone, 
                key='client_phone_input'
            )
            client_address = st.text_area("Адрес Доставки", key='client_address_input', height=80)
            
        with col2:
            st.subheader("Заявка и Дата")
            order_number = st.text_input(
                "Номер Заявки (внутренний)", 
                value=st.session_state.k_order_number,
                key='order_number_input'
            )
            delivery_date = st.date_input(
                "Дата Доставки", 
                value=st.session_state.k_delivery_date, 
                key='delivery_date_input'
            )
        
        # Отображение суммы внутри формы
        st.markdown("---")
        st.markdown(f"#### 💰 ИТОГО ПО ЗАКАЗУ: {total_sum:,.2f} РУБ.")
        
        # -------------------
        # РАЗДЕЛЕНИЕ КНОПОК
        # -------------------
        
        # Общий флаг блокировки для валидации
        is_disabled = (total_sum == 0 or not client_phone or not client_address)


        col_send, col_save = st.columns(2)
        
        with col_send:
            send_button = st.form_submit_button(
                "1. ОТПРАВИТЬ УВЕДОМЛЕНИЕ В WHATSAPP", 
                type="primary",
                disabled=is_disabled
            )


        with col_save:
            save_button = st.form_submit_button(
                "2. СОХРАНИТЬ ЗАЯВКУ В CRM", 
                type="secondary",
                disabled=is_disabled
            )




        if send_button or save_button:
            
            # Повторная валидация данных при нажатии любой из кнопок
            if total_sum == 0:
                st.warning("Нельзя отправить пустой заказ.")
            elif not client_phone or not client_address:
                st.warning("Пожалуйста, заполните все обязательные поля (Телефон, Адрес).")
            else:
                # Сбор данных в словарь для передачи функциям
                form_data = {
                    'order_number': order_number,
                    'client_phone': client_phone,
                    'client_address': client_address,
                    'delivery_date': delivery_date
                }
                
                if send_button:
                    display_whatsapp_notification(total_sum, order_items_text, form_data)
                
                if save_button:
                    save_order_to_gsheets(total_sum, order_items_text, form_data)




    st.divider()
    
    # ----------------------------------------------------
    # 3. КАЛЬКУЛЯТОР
    # ----------------------------------------------------
    
    st.header("3. Добавление позиций в Заказ")
    
    # Блок добавления
    col_select, col_qty, col_add = st.columns([5, 2, 1])
    
    with col_select:
        st.selectbox(
            "Выберите позицию из прайса", 
            options=price_items, 
            key='new_item_select'
        )
    with col_qty:
        st.number_input(
            "Количество", 
            min_value=1, 
            value=1, 
            step=1, 
            key='new_item_qty'
        )
    with col_add:
        # Пустая строка для выравнивания
        st.markdown(" ") 
        st.button("➕ ДОБАВИТЬ", on_click=add_item, type="secondary")


    # -------------------
    # ТАБЛИЦА ЗАКАЗА
    # -------------------
    
    if st.session_state.calculator_items:
        st.markdown("---")
        st.subheader("Текущий состав:")
        
        # Заголовки таблицы
        col_h_name, col_h_qty, col_h_price, col_h_sum, col_h_del = st.columns([4, 2, 2, 2, 1])
        col_h_name.markdown('**НАИМЕНОВАНИЕ**')
        col_h_qty.markdown('**КОЛ-ВО**')
        col_h_price.markdown('**ЦЕНА/ЕД**')
        col_h_sum.markdown('**СУММА**')


        # Отображение позиций и кнопки удаления
        for i, item in enumerate(st.session_state.calculator_items):
            col_i_name, col_i_qty, col_i_price, col_i_sum, col_i_del = st.columns([4, 2, 2, 2, 1])
            
            col_i_name.write(item['НАИМЕНОВАНИЕ'])
            col_i_qty.write(f"{item['КОЛИЧЕСТВО']}")
            col_i_price.write(f"{item['ЦЕНА_ЗА_ЕД']:,.2f}")
            col_i_sum.write(f"**{item['СУММА']:,.2f}**")
            
            col_i_del.button("❌", key=f'del_item_{i}', on_click=remove_item, args=(i,))


    else:
        st.info("Список заказа пуст. Используйте раздел выше для добавления товаров.")