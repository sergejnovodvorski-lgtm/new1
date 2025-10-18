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
[span_0](start_span)SPREADSHEET_NAME = "Start"[span_0](end_span)
[span_1](start_span)WORKSHEET_NAME_ORDERS = "ЗАЯВКИ"[span_1](end_span)
[span_2](start_span)WORKSHEET_NAME_PRICE = "ПРАЙС"[span_2](end_span)


# ВАЖНО: Колонка в Google Sheets называется "ДАТА ДОСТАВКИ" (с пробелом)
[span_3](start_span)DELIVERY_DATE_COLUMN_NAME = "ДАТА ДОСТАВКИ"[span_3](end_span) 




EXPECTED_HEADERS = [
    "ДАТА_ВВОДА",
    "НОМЕР_ЗАЯВКИ",
    "ТЕЛЕФОН",
    "АДРЕС",
    DELIVERY_DATE_COLUMN_NAME, 
    "КОММЕНТАРИЙ",
    "ЗАКАЗ",
    "СУММА"
[span_4](start_span)]




# Индекс столбца для сортировки/вставки: ДАТА ДОСТАВКИ (Е)
DELIVERY_DATE_COLUMN_INDEX = 5[span_4](end_span)




[span_5](start_span)MANAGER_WHATSAPP_PHONE = "79000000000"[span_5](end_span)
[span_6](start_span)TIME_STEP_SECONDS = 1800[span_6](end_span) # 30 минут


# --- ФОРМАТЫ ДАТЫ ---
# ИСПРАВЛЕНО: Убедимся, что формат для сохранения и парсинга одинаковый и ПОЛНЫЙ (с секундами)
[span_7](start_span)SHEET_DATETIME_FORMAT = '%d.%m.%Y %H:%M:%S'[span_7](end_span) 
[span_8](start_span)PARSE_DATETIME_FORMAT = '%d.%m.%Y %H:%M:%S'[span_8](end_span)
[span_9](start_span)DISPLAY_DATE_FORMAT = '%d.%m.%Y %H:%M'[span_9](end_span)




st.set_page_config(
    page_title="CRM: Ввод Новой Заявки",
    layout="wide",
    initial_sidebar_state="expanded"
[span_10](start_span))




# ==================
# БАЗОВЫЕ ФУНКЦИИ (Работа с данными и Google Sheets)
# ==================




@st.cache_resource(ttl=3600)
def get_gsheet_client():
    if "gcp_service_account" not in st.secrets:
        st.error("Секрет 'gcp_service_account' не найден. Проверьте конфигурацию secrets.toml.")[span_10](end_span)
        return None
    try:
        [span_11](start_span)return gspread.service_account_from_dict(st.secrets["gcp_service_account"])[span_11](end_span)
    except Exception as e:
        [span_12](start_span)st.error(f"Ошибка аутентификации: {e}")[span_12](end_span)
        return None




@st.cache_resource
def get_orders_worksheet():
    gc = get_gsheet_client()
    if not gc:
        return None
    try:
        [span_13](start_span)sh = gc.open(SPREADSHEET_NAME)[span_13](end_span)
        [span_14](start_span)worksheet = sh.worksheet(WORKSHEET_NAME_ORDERS)[span_14](end_span)
    
        [span_15](start_span)current_headers = worksheet.row_values(1)[span_15](end_span)
        if current_headers != EXPECTED_HEADERS:
            [span_16](start_span)worksheet.update('A1:H1', [EXPECTED_HEADERS])[span_16](end_span)
        return worksheet
    except Exception as e:
        [span_17](start_span)st.error(f"Ошибка доступа к листу '{WORKSHEET_NAME_ORDERS}': {e}")[span_17](end_span)
        return None




@st.cache_data(ttl="1h")
def load_all_orders():
    orders_ws = get_orders_worksheet()
    if not orders_ws:
        [span_18](start_span)return pd.DataFrame()[span_18](end_span)
    try:
      
        [span_19](start_span)data = orders_ws.get_all_records()[span_19](end_span)
        [span_20](start_span)df = pd.DataFrame(data)[span_20](end_span)
        return df
    except Exception as e:
        [span_21](start_span)st.error(f"Ошибка загрузки списка заявок: {e}")[span_21](end_span)
        return pd.DataFrame()




@st.cache_data(ttl="1h")
def load_price_list():
    gc = get_gsheet_client()
    if not gc:
        [span_22](start_span)return pd.DataFrame()[span_22](end_span)
    try:
        [span_23](start_span)sh = gc.open(SPREADSHEET_NAME)[span_23](end_span)
        [span_24](start_span)worksheet = sh.worksheet(WORKSHEET_NAME_PRICE)[span_24](end_span)
   
        [span_25](start_span)data = worksheet.get_all_records()[span_25](end_span)
        [span_26](start_span)df = pd.DataFrame(data)[span_26](end_span)




        if 'НАИМЕНОВАНИЕ' not in df.columns or 'ЦЕНА' not in df.columns:
            [span_27](start_span)st.error("В прайсе отсутствуют обязательные столбцы: 'НАИМЕНОВАНИЕ' или 'ЦЕНА'.")[span_27](end_span)
            return pd.DataFrame()




        [span_28](start_span)df['ЦЕНА'] = pd.to_numeric(df['ЦЕНА'], errors='coerce')[span_28](end_span)
        [span_29](start_span)df.dropna(subset=['ЦЕНА'], inplace=True)[span_29](end_span)
        return df
    [span_30](start_span)except Exception as e:[span_30](end_span)
        [span_31](start_span)st.error(f"Ошибка загрузки прайса: {e}")[span_31](end_span)
        return pd.DataFrame()




def is_valid_phone(phone: str) -> str:
    [span_32](start_span)normalized = re.sub(r'\D', '', phone)[span_32](end_span)
    if normalized.startswith('8') and len(normalized) == 11:
        [span_33](start_span)normalized = '7' + normalized[1:][span_33](end_span)
    if len(normalized) == 11 and normalized.startswith('7'):
        [span_34](start_span)return normalized[span_34](end_span)
    [span_35](start_span)return ""[span_35](end_span)




def get_default_delivery_date():
    [span_36](start_span)return datetime.today().date() + timedelta(days=1)[span_36](end_span)




def get_default_delivery_time():
    [span_37](start_span)return time(10, 0)[span_37](end_span)




# ======
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ (Логика приложения)
# ===================




[span_38](start_span)def generate_next_order_number():[span_38](end_span)
    """Генерирует следующий номер заявки"""
    try:
        [span_39](start_span)df = load_all_orders()[span_39](end_span)
        if not df.empty and 'НОМЕР_ЗАЯВКИ' in df.columns:
            # Преобразуем номера в int, игнорируя нечисловые значения
            [span_40](start_span)order_numbers = [int(n) for n in df['НОМЕР_ЗАЯВКИ'] if str(n).isdigit()][span_40](end_span)
            [span_41](start_span)return str(max(order_numbers) + 1) if order_numbers else "1001"[span_41](end_span)
        else:
            [span_42](start_span)return "1001"[span_42](end_span)
    except:
 
        [span_43](start_span)return "1001"[span_43](end_span)




def parse_order_text_to_items(order_text: str) -> List[Dict[str, Any]]:
    items = []
    # Паттерн: Наименование - Количество шт. (по Цена РУБ.) | Комментарий
    [span_44](start_span)pattern = re.compile(r'(.+?) - (\d+)\s*шт\.\s*\(по\s*([\d\s,.]+)\s*РУБ\.\)(?:\s*\|\s*(.*))?')[span_44](end_span)




    for line in order_text.split('\n'):
        [span_45](start_span)match = pattern.search(line.strip())[span_45](end_span)
        if match:
            [span_46](start_span)name = match.group(1).strip()[span_46](end_span)
            [span_47](start_span)qty = int(match.group(2))[span_47](end_span)
            [span_48](start_span)price_str_raw = match.group(3)[span_48](end_span)
            
        
            # Более надежный парсинг цены
            [span_49](start_span)price_str_cleaned = price_str_raw.replace(' ', "").replace(',', '.')[span_49](end_span)
            [span_50](start_span)price_str = re.sub(r'[^\d.]', '', price_str_cleaned)[span_50](end_span)
            
            [span_51](start_span)comment = match.group(4).strip() if match.group(4) else ""[span_51](end_span)
            
            try:
     
                [span_52](start_span)price_per_unit = float(price_str)[span_52](end_span)
            except ValueError:
                [span_53](start_span)price_per_unit = 0.0[span_53](end_span)




            items.append({
                'НАИМЕНОВАНИЕ': name,
                'КОЛИЧЕСТВО': qty,
         
                [span_54](start_span)'ЦЕНА_ЗА_ЕД': price_per_unit,[span_54](end_span)
                [span_55](start_span)'СУММА': price_per_unit * qty,[span_55](end_span)
                [span_56](start_span)'КОММЕНТАРИЙ_ПОЗИЦИИ': comment[span_56](end_span)
            })
    return items




def get_insert_index(new_delivery_date_str: str, orders_ws) -> int:
    [span_57](start_span)if not orders_ws: return 2[span_57](end_span)
    try:
        # Получаем значения, начиная со второй строки (пропуская заголовки)
        [span_58](start_span)data_col = orders_ws.col_values(DELIVERY_DATE_COLUMN_INDEX)[1:][span_58](end_span)
    except Exception:
       
        [span_59](start_span)return 2[span_59](end_span)
    
    [span_60](start_span)if not data_col: return 2[span_60](end_span)
    
    try:
        # Парсим новую дату в полном формате
        [span_61](start_span)new_date = datetime.strptime(new_delivery_date_str, PARSE_DATETIME_FORMAT)[span_61](end_span)
    except ValueError:
        return 2




    for i, date_str in enumerate(data_col):
        try:
            # Парсим существующие даты в полном формате
            [span_62](start_span)existing_date = datetime.strptime(date_str, PARSE_DATETIME_FORMAT)[span_62](end_span)
            if new_date <= existing_date:
       
                return i + 2 # +2, потому что i=0 это вторая строка листа
        except ValueError:
            continue
            
    [span_63](start_span)return len(data_col) + 2[span_63](end_span)




def save_order_data(data_row: List[Any], orders_ws) -> bool:
    [span_64](start_span)if not orders_ws: return False[span_64](end_span)
    try:
        [span_65](start_span)new_delivery_date_str = data_row[4][span_65](end_span)
        [span_66](start_span)insert_index = get_insert_index(new_delivery_date_str, orders_ws)[span_66](end_span)
        [span_67](start_span)orders_ws.insert_row(data_row, index=insert_index)[span_67](end_span)
 
        [span_68](start_span)load_all_orders.clear()[span_68](end_span)
        return True
    except Exception as e:
        [span_69](start_span)st.error(f"Ошибка сохранения заявки: {e}")[span_69](end_span)
        return False




def update_order_data(order_number: str, data_row: List[Any], orders_ws) -> bool:
    [span_70](start_span)if not orders_ws: return False[span_70](end_span)
    try:
        # Используем индекс колонки НОМЕР_ЗАЯВКИ (2)
        [span_71](start_span)col_values = orders_ws.col_values(2)[span_71](end_span) 
        target_gspread_row_index = -1
        # Ищем с конца, чтобы найти последнюю запись (если есть дубли)
        for i in range(len(col_values) - 1, 0, -1):
   
            [span_72](start_span)if str(col_values[i]) == order_number:[span_72](end_span)
                target_gspread_row_index = i + 1
                break




        if target_gspread_row_index == -1:
            [span_73](start_span)st.error(f"Заявка с номером {order_number} не найдена в таблице.")[span_73](end_span)
            return False




        orders_ws.update(f'A{target_gspread_row_index}:H{target_gspread_row_index}',
 
                         [span_74](start_span)[data_row])[span_74](end_span)
        [span_75](start_span)load_all_orders.clear()[span_75](end_span)
        return True
    except Exception as e:
        [span_76](start_span)st.error(f"Ошибка обновления заявки: {e}")[span_76](end_span)
        return False




def generate_whatsapp_url(target_phone: str, order_data: Dict[str, str], total_sum: float) -> str:
    [span_77](start_span)text = f"Здравствуйте[span_77](end_span)! Пожалуйста, проверьте детали вашего заказа:\n\n"
    [span_78](start_span)text += f"*Номер Заявки:* {order_data['НОМЕР_ЗАЯВКИ']}\n"[span_78](end_span)
    [span_79](start_span)text += f"*Телефон:* {order_data['ТЕЛЕФОН']}\n"[span_79](end_span)
    [span_80](start_span)text += f"*Адрес:* {order_data['АДРЕС']}\n"[span_80](end_span)
    [span_81](start_span)text += f"*Дата и Время Доставки:* {order_data[DELIVERY_DATE_COLUMN_NAME]}\n"[span_81](end_span) 
    if order_data.get('КОММЕНТАРИЙ'):
        [span_82](start_span)text += f"*Комментарий к заказу (общий):* {order_data['КОММЕНТАРИЙ']}\n"[span_82](end_span)
    
    [span_83](start_span)text += f"\n*Состав Заказа:*\n{order_data['ЗАКАЗ']}\n\n"[span_83](end_span)
    [span_84](start_span)text += f"*ИТОГО: {total_sum:,.2f} РУБ.*\n\n"[span_84](end_span)
    [span_85](start_span)text += "Пожалуйста, подтвердите заказ или укажите необходимые изменения."[span_85](end_span)
    
    [span_86](start_span)encoded_text = urllib.parse.quote(text)[span_86](end_span)
   
    [span_87](start_span)normalized_phone = is_valid_phone(target_phone)[span_87](end_span)
    if not normalized_phone:
        [span_88](start_span)target_phone_final = MANAGER_WHATSAPP_PHONE[span_88](end_span)
    else:
        [span_89](start_span)target_phone_final = normalized_phone[span_89](end_span)
        
    [span_90](start_span)return f"https://wa.me/{target_phone_final}?text={encoded_text}"[span_90](end_span)




def format_datetime_for_display(dt_str):
    """Форматирует дату-время для отображения"""
    if not isinstance(dt_str, str):
        [span_91](start_span)return str(dt_str)[span_91](end_span)
        
    try:
        # Пробуем распарсить в полном формате сохранения (включая секунды)
    
        [span_92](start_span)dt = datetime.strptime(dt_str, PARSE_DATETIME_FORMAT)[span_92](end_span)
        [span_93](start_span)return dt.strftime(DISPLAY_DATE_FORMAT)[span_93](end_span)
    except ValueError:
        try:
            # Пробуем альтернативный формат, если основной не сработал (без секунд)
            [span_94](start_span)dt = datetime.strptime(dt_str, '%d.%m.%Y %H:%M')[span_94](end_span)
            [span_95](start_span)return dt.strftime(DISPLAY_DATE_FORMAT)[span_95](end_span)
        except ValueError:
            # Если не удалось распарсить, возвращаем исходную строку
            [span_96](start_span)return dt_str[span_96](end_span)




# ============================
# ОСНОВНАЯ ЛОГИКА ПРИЛОЖЕНИЯ
# ============================




def main():
    # Инициализация основного состояния
    if 'app_mode' not in st.session_state:
        [span_97](start_span)st.session_state.app_mode = 'new'[span_97](end_span)
    if 'calculator_items' not in st.session_state:
        [span_98](start_span)st.session_state.calculator_items = [][span_98](end_span)
    if 'last_success_message' not in st.session_state:
        [span_99](start_span)st.session_state.last_success_message = None[span_99](end_span)
    if 'form_reset_trigger' not in st.session_state:
       
        [span_100](start_span)st.session_state.form_reset_trigger = False[span_100](end_span)
    if 'loaded_order_data' not in st.session_state:
        [span_101](start_span)st.session_state.loaded_order_data = None[span_101](end_span)
    if 'form_key' not in st.session_state:
        [span_102](start_span)st.session_state.form_key = 0[span_102](end_span)




    # Обработка сброса формы
    if st.session_state.form_reset_trigger:
        [span_103](start_span)st.session_state.form_reset_trigger = False[span_103](end_span)
        [span_104](start_span)st.session_state.app_mode = 'new'[span_104](end_span)
        [span_105](start_span)st.session_state.calculator_items = [][span_105](end_span)
        [span_106](start_span)st.session_state.last_success_message = None[span_106](end_span)
        [span_107](start_span)st.session_state.loaded_order_data = None[span_107](end_span)
        [span_108](start_span)st.session_state.form_key += 1[span_108](end_span) 
        st.rerun()




    # Загрузка данных
    [span_109](start_span)price_df = load_price_list()[span_109](end_span)
    [span_110](start_span)orders_ws = get_orders_worksheet()[span_110](end_span)
    
    [span_111](start_span)price_items = ["--- Выберите позицию ---"] + price_df['НАИМЕНОВАНИЕ'].tolist() if not price_df.empty else ["--- Прайс не загружен ---"][span_111](end_span)




    [span_112](start_span)st.title("CRM: Управление Заявками")[span_112](end_span)




    # Обработка успешного сообщения
    if st.session_state.last_success_message:
        [span_113](start_span)st.success(st.session_state.last_success_message)[span_113](end_span)
        [span_114](start_span)st.session_state.last_success_message = None[span_114](end_span)




  
    # ====================
    # ГЛАВНОЕ РАЗДЕЛЕНИЕ НА ВКЛАДКИ
    # ====================
    [span_115](start_span)tab_order_entry, tab_order_list = st.tabs(["Ввод/Редактирование Заявки", "Список Заявок"])[span_115](end_span)




    # ====================
    # ВКЛАДКА 1: ВВОД/РЕДАКТИРОВАНИЕ ЗАЯВКИ
    # ====================
    with tab_order_entry:
        [span_116](start_span)st.subheader("Выбор Режима Работы")[span_116](end_span)
        
        mode = st.radio(
            "Выберите действие:",
          
            [span_117](start_span)['Новая заявка', 'Редактировать существующую'],[span_117](end_span)
            horizontal=True,
            key='mode_selector'
        )




        if mode == 'Новая заявка' and st.session_state.app_mode != 'new':
            [span_118](start_span)st.session_state.app_mode = 'new'[span_118](end_span)
            [span_119](start_span)st.session_state.calculator_items = [][span_119](end_span)
            [span_120](start_span)st.session_state.loaded_order_data = None[span_120](end_span)
     
            [span_121](start_span)st.session_state.form_key += 1[span_121](end_span)
            st.rerun()




        elif mode == 'Редактировать существующую' and st.session_state.app_mode != 'edit':
            [span_122](start_span)st.session_state.app_mode = 'edit'[span_122](end_span)
            [span_123](start_span)st.session_state.calculator_items = [][span_123](end_span)
            [span_124](start_span)st.session_state.loaded_order_data = None[span_124](end_span)
            [span_125](start_span)st.session_state.form_key += 1[span_125](end_span)
       
            [span_126](start_span)st.rerun()[span_126](end_span)
            
        st.info("**Режим Создания Новой Заявки**" if st.session_state.app_mode == 'new'
                [span_127](start_span)else "**Режим Редактирования/Перезаписи**")[span_127](end_span)
        
        # ====================
        # ПОИСК СУЩЕСТВУЮЩЕЙ ЗАЯВКИ
        # ====================
        if st.session_state.app_mode == 'edit':
  
            [span_128](start_span)st.subheader("Поиск заявки для редактирования")[span_128](end_span)
            [span_129](start_span)search_number = st.text_input("Введите номер заявки для поиска:", key='search_input')[span_129](end_span)
            
            [span_130](start_span)if st.button("🔎 Найти и загрузить заявку", use_container_width=True):[span_130](end_span)
                if search_number and orders_ws:
                   
                    [span_131](start_span)try:[span_131](end_span)
                        [span_132](start_span)df = load_all_orders()[span_132](end_span)
                        [span_133](start_span)target_rows = df[df['НОМЕР_ЗАЯВКИ'].astype(str) == search_number][span_133](end_span)




                        if not target_rows.empty:
                   
                            [span_134](start_span)row = target_rows.iloc[-1].to_dict()[span_134](end_span)




                            st.session_state.loaded_order_data = {
                                'order_number': str(row.get('НОМЕР_ЗАЯВКИ', "")),
                         
                                [span_135](start_span)'client_phone': str(row.get('ТЕЛЕФОН', "")),[span_135](end_span)
                                [span_136](start_span)'address': str(row.get('АДРЕС', "")),[span_136](end_span)
                                [span_137](start_span)'comment': str(row.get('КОММЕНТАРИЙ', "")),[span_137](end_span)
                       
                                [span_138](start_span)'calculator_items': parse_order_text_to_items(str(row.get('ЗАКАЗ', "")))[span_138](end_span)
                            }




                            [span_139](start_span)delivery_dt_str = str(row.get(DELIVERY_DATE_COLUMN_NAME, ""))[span_139](end_span)
                            try:
 
                                [span_140](start_span)dt_obj = datetime.strptime(delivery_dt_str, PARSE_DATETIME_FORMAT)[span_140](end_span)
                                [span_141](start_span)st.session_state.loaded_order_data['delivery_date'] = dt_obj.date()[span_141](end_span)
                                
                                [span_142](start_span)st.session_state.loaded_order_data['delivery_time'] = dt_obj.time()[span_142](end_span)
                            except (ValueError, TypeError):
                                [span_143](start_span)st.session_state.loaded_order_data['delivery_date'] = get_default_delivery_date()[span_143](end_span)
                                [span_144](start_span)st.session_state.loaded_order_data['delivery_time'] = get_default_delivery_time()[span_144](end_span)




                            [span_145](start_span)st.session_state.calculator_items = st.session_state.loaded_order_data['calculator_items'][span_145](end_span)




                            [span_146](start_span)st.session_state.form_key += 1[span_146](end_span) 
                            [span_147](start_span)st.success(f"Заявка №{search_number} загружена для редактирования.")[span_147](end_span)
       
                            [span_148](start_span)st.rerun()[span_148](end_span)
                        else:
                            [span_149](start_span)st.error(f"Заявка с номером {search_number} не найдена")[span_149](end_span)
                    [span_150](start_span)except Exception as e:[span_150](end_span)
                        [span_151](start_span)st.error(f"Ошибка при загрузке заявки: {e}")[span_151](end_span)
                else:
                    [span_152](start_span)st.error("Введите номер заявки")[span_152](end_span)
            [span_153](start_span)st.markdown("---")[span_153](end_span)




        # ====================
        # ОСНОВНАЯ ФОРМА
  
        # ====================
        [span_154](start_span)st.subheader("Основные Данные Заявки")[span_154](end_span)
        
        [span_155](start_span)form_key = st.session_state.form_key[span_155](end_span)
        
        if st.session_state.app_mode == 'new':
            [span_156](start_span)default_order_number = generate_next_order_number()[span_156](end_span)
            default_client_phone = ""
            default_address = ""
    
            [span_157](start_span)default_comment = ""[span_157](end_span)
            [span_158](start_span)default_delivery_date = get_default_delivery_date()[span_158](end_span)
            [span_159](start_span)default_delivery_time = get_default_delivery_time()[span_159](end_span)
        else:
            if st.session_state.loaded_order_data:
                [span_160](start_span)default_order_number = st.session_state.loaded_order_data.get('order_number', "")[span_160](end_span)
                [span_161](start_span)default_client_phone = st.session_state.loaded_order_data.get('client_phone', "")[span_161](end_span)
   
                [span_162](start_span)default_address = st.session_state.loaded_order_data.get('address', "")[span_162](end_span)
                [span_163](start_span)default_comment = st.session_state.loaded_order_data.get('comment', "")[span_163](end_span)
                [span_164](start_span)default_delivery_date = st.session_state.loaded_order_data.get('delivery_date', get_default_delivery_date())[span_164](end_span)
                [span_165](start_span)default_delivery_time = st.session_state.loaded_order_data.get('delivery_time', get_default_delivery_time())[span_165](end_span)
            else:
               
                [span_166](start_span)default_order_number = ""[span_166](end_span)
                default_client_phone = ""
                default_address = ""
                default_comment = ""
                default_delivery_date = get_default_delivery_date()
                [span_167](start_span)default_delivery_time = get_default_delivery_time()[span_167](end_span)




       
        [span_168](start_span)col1, col2 = st.columns([1, 3])[span_168](end_span)
        [span_169](start_span)col3, col4 = st.columns(2)[span_169](end_span)




        with col1:
            if st.session_state.app_mode == 'new':
                order_number = st.text_input(
         
                    [span_170](start_span)"Номер Заявки",[span_170](end_span)
                    value=default_order_number,
                    key=f'order_number_new_{form_key}'
                )
            else:
                order_number = st.text_input(
  
                    [span_171](start_span)"Номер Заявки",[span_171](end_span)
                    value=default_order_number,
                    key=f'order_number_edit_{form_key}',
                    disabled=True 
                )
    
                     
        with col2:
            # Используем st.text_area с минимальной высотой для расширения поля ввода телефона
            client_phone = st.text_area(
                "Телефон Клиента (с 7)",
                value=default_client_phone,
      
                [span_172](start_span)height=30, # Устанавливаем минимальную высоту, чтобы выглядело как однострочный ввод[span_172](end_span)
                key=f'client_phone_{form_key}'
            )




        with col3:
            delivery_date = st.date_input(
                "Дата Доставки",
             
                [span_173](start_span)value=default_delivery_date,[span_173](end_span)
                min_value=datetime.today().date(),
                key=f'delivery_date_{form_key}',
                format="DD.MM.YYYY"
            )




        with col4:
            delivery_time = st.time_input(
              
                [span_174](start_span)"Время Доставки (интервал 30 мин)",[span_174](end_span)
                value=default_delivery_time,
                step=TIME_STEP_SECONDS,
                key=f'delivery_time_{form_key}'
            )




        address = st.text_input(
            "Адрес Доставки",
           
            [span_175](start_span)value=default_address,[span_175](end_span)
            key=f'address_{form_key}'
        )




        comment = st.text_area(
            "Комментарий / Примечание к заказу (общий)",
            value=default_comment,
            height=50,
            key=f'comment_{form_key}'
        )
        
 
        [span_176](start_span)st.markdown("---")[span_176](end_span)




        # =========================================================
        # КАЛЬКУЛЯТОР ЗАКАЗА
        # =========================================================
        [span_177](start_span)st.subheader("Состав Заказа (Калькулятор)")[span_177](end_span)
        
        current_qty = 1
        current_comment = ""
        
        [span_178](start_span)col_item, col_qty = st.columns([5, 1])[span_178](end_span)
      
        with col_item:
            selected_item = st.selectbox(
                "Выбор позиции",
                price_items,
                disabled=price_df.empty,
                key=f'item_selector_{form_key}'
          
            [span_179](start_span))
        
        with col_qty:
            current_qty = st.number_input(
                "Кол-во",
                min_value=1,
                step=1,
                value=1,
   
                key=f'item_qty_{form_key}'[span_179](end_span)
            )
        
        [span_180](start_span)col_comment, col_add = st.columns([5, 1])[span_180](end_span)
        
        with col_comment:
            current_comment = st.text_input(
                "Комментарий к позиции",
      
                [span_181](start_span)value="",[span_181](end_span)
                key=f'item_comment_{form_key}'
            )
            
        with col_add:
            st.markdown(" ")
            if st.button(
               
                [span_182](start_span)"➕ Добавить",[span_182](end_span)
                use_container_width=True,
                disabled=selected_item == price_items[0],
                key=f'add_item_button_{form_key}'
            ):
                if selected_item != price_items[0]:
                 
                    [span_183](start_span)price_row = price_df[price_df['НАИМЕНОВАНИЕ'] == selected_item][span_183](end_span)
                    if not price_row.empty:
                        [span_184](start_span)price = float(price_row.iloc[0]['ЦЕНА'])[span_184](end_span)
                        
                     
                        st.session_state.calculator_items.append({
                            [span_185](start_span)'НАИМЕНОВАНИЕ': selected_item,[span_185](end_span)
                            [span_186](start_span)'КОЛИЧЕСТВО': current_qty,[span_186](end_span)
                            [span_187](start_span)'ЦЕНА_ЗА_ЕД': price,[span_187](end_span)
          
                            [span_188](start_span)'СУММА': price * current_qty,[span_188](end_span)
                            [span_189](start_span)'КОММЕНТАРИЙ_ПОЗИЦИИ': current_comment[span_189](end_span)
                        })
                        st.rerun()




  
        # Отображение товаров
        total_sum = 0
        [span_190](start_span)if st.session_state.calculator_items:[span_190](end_span)
            [span_191](start_span)df_items = pd.DataFrame(st.session_state.calculator_items)[span_191](end_span)
            [span_192](start_span)total_sum = df_items['СУММА'].sum()[span_192](end_span)
            
            st.dataframe(
                df_items[['НАИМЕНОВАНИЕ', 'КОЛИЧЕСТВО', 'ЦЕНА_ЗА_ЕД', 'КОММЕНТАРИЙ_ПОЗИЦИИ', 'СУММА']],
 
                [span_193](start_span)column_config={[span_193](end_span)
                    'НАИМЕНОВАНИЕ': 'Товар',
                    'КОЛИЧЕСТВО': 'Кол-во',
                    'ЦЕНА_ЗА_ЕД': st.column_config.NumberColumn("Цена за ед.", format="%.2f РУБ."),
                  
                    [span_194](start_span)'КОММЕНТАРИЙ_ПОЗИЦИИ': 'Комментарий',[span_194](end_span)
                    'СУММА': st.column_config.NumberColumn("Сумма", format="%.2f РУБ."),
                },
                hide_index=True,
                use_container_width=True
            )




            # Удаление позиций
            [span_195](start_span)st.markdown("##### Удаление позиций:")[span_195](end_span)
            for i in range(len(st.session_state.calculator_items) - 1, -1, -1):
                item = st.session_state.calculator_items[i]
                [span_196](start_span)col_name, col_comment_text, col_sum, col_del = st.columns([4, 2, 1.5, 0.5])[span_196](end_span)
                
         
                with col_name:
                    [span_197](start_span)st.write(f"**{item['НАИМЕНОВАНИЕ']}** ({item['КОЛИЧЕСТВО']} шт.)")[span_197](end_span)
                with col_comment_text:
                    if item['КОММЕНТАРИЙ_ПОЗИЦИИ']:
                        [span_198](start_span)st.markdown(f"*{item['КОММЕНТАРИЙ_ПОЗИЦИИ']}*")[span_198](end_span)
        
                    else:
                        [span_199](start_span)st.write("-")[span_199](end_span)
                with col_sum:
                    [span_200](start_span)st.write(f"**{item['СУММА']:,.2f} РУБ.**")[span_200](end_span)
                with col_del:
         
                    [span_201](start_span)if st.button("❌", key=f"del_{i}_{form_key}"):[span_201](end_span)
                        st.session_state.calculator_items.pop(i)
                        st.rerun()




            [span_202](start_span)st.markdown(f"### 💰 **ИТОГО: {total_sum:,.2f} РУБ.**")[span_202](end_span)
        else:
            [span_203](start_span)st.info("В заказе пока нет позиций. Добавьте товар.")[span_203](end_span)




        [span_204](start_span)st.markdown("---")[span_204](end_span)
        
        # =========================================================
        # СОХРАНЕНИЕ ДАННЫХ
        # =========================================================
        [span_205](start_span)st.subheader("Завершение Заявки")[span_205](end_span)




        # Приводим значение text_area к строке и удаляем лишние пробелы/переносы
        phone_input = st.session_state.get(f'client_phone_{form_key}', default_client_phone).strip().replace('\n', '')
        [span_206](start_span)valid_phone = is_valid_phone(phone_input)[span_206](end_span)
     
        is_ready_to_send = (
            order_number and
            valid_phone and
            address and
            st.session_state.calculator_items
        [span_207](start_span))




        if not is_ready_to_send:
            missing_fields = [][span_207](end_span)
    
            [span_208](start_span)if not order_number: missing_fields.append("Номер Заявки")[span_208](end_span)
            [span_209](start_span)if not phone_input: missing_fields.append("Телефон Клиента")[span_209](end_span)
            [span_210](start_span)elif not valid_phone: missing_fields.append("Телефон (неверный формат 7XXXXXXXXXX)")[span_210](end_span)
            [span_211](start_span)if not address: missing_fields.append("Адрес Доставки")[span_211](end_span)
            [span_212](start_span)if not st.session_state.calculator_items: missing_fields.append("Состав Заказа")[span_212](end_span)
            if missing_fields:
         
                [span_213](start_span)st.error(f"❌ Заявка не готова к сохранению[span_213](end_span)! [span_214](start_span)Необходимо заполнить: {', '.join(missing_fields)}")[span_214](end_span)




        def format_order_item(item):
            # Формат сохранения: Наименование - Кол-во шт. (по Цена РУБ.) | Комментарий
            [span_215](start_span)base = f"{item['НАИМЕНОВАНИЕ']} - {item['КОЛИЧЕСТВО']} шт.[span_215](end_span) (по {item['ЦЕНА_ЗА_ЕД']:,.2f} РУБ.)"
            if item.get('КОММЕНТАРИЙ_ПОЗИЦИИ'):
                [span_216](start_span)base += f" |[span_216](end_span) {item['КОММЕНТАРИЙ_ПОЗИЦИИ']}"
            return base
            
        [span_217](start_span)order_details = "\n".join([format_order_item(item) for item in st.session_state.calculator_items])[span_217](end_span)




        entry_datetime = datetime.now()
        [span_218](start_span)entry_datetime_str = entry_datetime.strftime(SHEET_DATETIME_FORMAT)[span_218](end_span)
        
        delivery_datetime = datetime.combine(delivery_date, delivery_time)
        [span_219](start_span)delivery_datetime_str = delivery_datetime.strftime(SHEET_DATETIME_FORMAT)[span_219](end_span)
        
    
        data_to_save = [
            [span_220](start_span)entry_datetime_str, # 0. ДАТА_ВВОДА[span_220](end_span)
            [span_221](start_span)order_number,       # 1. НОМЕР_ЗАЯВКИ[span_221](end_span)
            [span_222](start_span)valid_phone,        # 2. ТЕЛЕФОН[span_222](end_span)
            [span_223](start_span)address,            # 3. АДРЕС[span_223](end_span)
          
            [span_224](start_span)delivery_datetime_str, # 4. ДАТА ДОСТАВКИ[span_224](end_span)
            [span_225](start_span)comment,            # 5. КОММЕНТАРИЙ (Общий к заказу)[span_225](end_span)
            [span_226](start_span)order_details,      # 6. ЗАКАЗ (Включает комментарии позиций)[span_226](end_span)
            [span_227](start_span)float(total_sum) if not math.isnan(total_sum) else 0.0 # 7. СУММА[span_227](end_span)
        ]
        
      
        [span_228](start_span)col_save1, col_save2 = st.columns(2)[span_228](end_span)
        with col_save1:
            if st.session_state.app_mode == 'new':
                [span_229](start_span)if st.button("💾 Сохранить Новую Заявку", disabled=not is_ready_to_send, type="primary", use_container_width=True, key=f'save_new_order_{form_key}'):[span_229](end_span)
                    if save_order_data(data_to_save, orders_ws):
                        
                        [span_230](start_span)st.session_state.last_success_message = f"🎉 Заявка №{order_number} успешно сохранена!"[span_230](end_span)
                        st.session_state.form_reset_trigger = True
            else:
                [span_231](start_span)if st.button("💾 Перезаписать Заявку", disabled=not is_ready_to_send, type="primary", use_container_width=True, key=f'update_order_{form_key}'):[span_231](end_span)
                    if update_order_data(order_number, data_to_save, orders_ws):
         
                        [span_232](start_span)st.session_state.last_success_message = f"🎉 Заявка №{order_number} успешно перезаписана!"[span_232](end_span)
                        st.session_state.loaded_order_data = None
                        st.rerun()




        with col_save2:
            [span_233](start_span)if st.button("🔄 Очистить форму", use_container_width=True, key=f'clear_form_{form_key}'):[span_233](end_span)
   
                st.session_state.form_reset_trigger = True
                st.rerun()




        if is_ready_to_send:
            whatsapp_data = {
                [span_234](start_span)'НОМЕР_ЗАЯВКИ': order_number,[span_234](end_span)
                'ТЕЛЕФОН': valid_phone,
            
                [span_235](start_span)'АДРЕС': address,[span_235](end_span)
                DELIVERY_DATE_COLUMN_NAME: delivery_datetime.strftime('%d.%m.%Y %H:%M'), 
                'КОММЕНТАРИЙ': comment,
                'ЗАКАЗ': order_details
            }
            [span_236](start_span)final_total_sum = float(total_sum) if not math.isnan(total_sum) else 0.0[span_236](end_span)
           
            [span_237](start_span)whatsapp_url = generate_whatsapp_url(valid_phone, whatsapp_data, final_total_sum)[span_237](end_span)
            
            st.markdown("---")
            st.markdown(f"**Ссылка для подтверждения клиенту ({valid_phone}):**")
            st.markdown(
                f'<a href="{whatsapp_url}" target="_blank">'
                f'<button style="background-color:#25D366;color:white;padding:10px 20px;border:none;border-radius:5px;cursor:pointer;width:100%;">'
       
                [span_238](start_span)f'💬 Открыть WhatsApp с Заказом'[span_238](end_span)
                f'</button></a>',
                unsafe_allow_html=True
            )
        
    # =========================================================
    # ВКЛАДКА 2: СПИСОК ЗАЯВОК (ИСПРАВЛЕННАЯ ВЕРСИЯ)
    # =========================================================
    with tab_order_list:
        [span_239](start_span)st.header("📋 Просмотр и Поиск Заявок")[span_239](end_span)




        [span_240](start_span)all_orders_df = load_all_orders()[span_240](end_span)




        if all_orders_df.empty:
            [span_241](start_span)st.warning("Лист 'ЗАЯВКИ' пуст или произошла ошибка при загрузке.")[span_241](end_span)
        else:
            [span_242](start_span)df_display = all_orders_df.copy()[span_242](end_span)




            [span_243](start_span)df_display['НОМЕР_ЗАЯВКИ'] = df_display['НОМЕР_ЗАЯВКИ'].astype(str)[span_243](end_span)
            [span_244](start_span)df_display['СУММА'] = pd.to_numeric(df_display['СУММА'], errors='coerce').fillna(0)[span_244](end_span)




         
            [span_245](start_span)df_display['ДАТА_ВВОДА_ОТОБРАЖЕНИЕ'] = df_display['ДАТА_ВВОДА'].apply(format_datetime_for_display)[span_245](end_span)
            
            [span_246](start_span)df_display['ДАТА_ДОСТАВКИ_ОТОБРАЖЕНИЕ'] = df_display[DELIVERY_DATE_COLUMN_NAME].apply(format_datetime_for_display)[span_246](end_span)




            try:
                [span_247](start_span)df_display['ДАТА_ДОСТАВКИ_DT'] = pd.to_datetime(df_display[DELIVERY_DATE_COLUMN_NAME], format=PARSE_DATETIME_FORMAT, errors='coerce')[span_247](end_span)
            except:
                # Если парсинг с форматом не удался, пробуем без него
                [span_248](start_span)df_display['ДАТА_ДОСТАВКИ_DT'] = pd.to_datetime(df_display[DELIVERY_DATE_COLUMN_NAME], errors='coerce')[span_248](end_span)
      
       
            # Заменяем \n на HTML-тег <br> для переноса строк в ячейке ЗАКАЗ
            [span_249](start_span)df_display['ЗАКАЗ'] = df_display['ЗАКАЗ'].str.replace('\n', '<br>', regex=False)[span_249](end_span)








            # 2. Поиск и фильтрация
            [span_250](start_span)st.subheader("Поиск")[span_250](end_span)
            [span_251](start_span)search_term = st.text_input("🔍 Введите № заявки, телефон или часть адреса:", key='order_search_list')[span_251](end_span)




     
            [span_252](start_span)if search_term:[span_252](end_span)
                search_lower = search_term.lower()
                df_display = df_display[
                    [span_253](start_span)df_display['НОМЕР_ЗАЯВКИ'].str.contains(search_lower, na=False) |[span_253](end_span)
                    [span_254](start_span)df_display['ТЕЛЕФОН'].astype(str).str.contains(search_lower, na=False) |[span_254](end_span)
                    [span_255](start_span)df_display['АДРЕС'].astype(str).str.contains(search_lower, case=False, na=False)[span_255](end_span)
                ]
                [span_256](start_span)st.info(f"Отображается заявок: **{len(df_display)}**")[span_256](end_span)




            # 3. Визуально красивый вывод с исправленными датами
            # ИСПРАВЛЕНО: Убрано 'ЗАКАЗ_HTML', заменено на 'ЗАКАЗ' для устранения KeyError
            display_columns = [
                'ДАТА_ВВОДА_ОТОБРАЖЕНИЕ', 'НОМЕР_ЗАЯВКИ', 'ТЕЛЕФОН', 'АДРЕС',
         
                'ДАТА_ДОСТАВКИ_ОТОБРАЖЕНИЕ', 'КОММЕНТАРИЙ', 'ЗАКАЗ', 'СУММА' # <--- ИСПРАВЛЕНИЕ КЛЮЧА
            [span_257](start_span)]
            
            st.dataframe(
                df_display.sort_values(by='ДАТА_ДОСТАВКИ_DT',
                                      
                    ascending=True)[display_columns],[span_257](end_span)
                column_config={
                    "ДАТА_ВВОДА_ОТОБРАЖЕНИЕ": st.column_config.TextColumn("Введено", width="small"),
                    "НОМЕР_ЗАЯВКИ": st.column_config.TextColumn("№ Заявки", width="small"),
                    "ТЕЛЕФОН": st.column_config.TextColumn("📞 Телефон", width="medium"), 
              
                    [span_258](start_span)"АДРЕС": st.column_config.TextColumn("📍 Адрес", width="large"),[span_258](end_span)
                    [span_259](start_span)"ДАТА_ДОСТАВКИ_ОТОБРАЖЕНИЕ": st.column_config.TextColumn("️🚚 Доставка", width="medium"),[span_259](end_span)
                    [span_260](start_span)"КОММЕНТАРИЙ": st.column_config.TextColumn("📝 Общий комм.", width="medium"),[span_260](end_span)
                    # ИСПРАВЛЕНО: Ключ 'ЗАКАЗ' настроен как HTML
                    "ЗАКАЗ": st.column_config.Column("🛒 Состав Заказа", width="large", is_html=True), 
                  
                    [span_261](start_span)"СУММА": st.column_config.NumberColumn("💰 Сумма", format="%.2f РУБ.", width="small")[span_261](end_span)
                },
                hide_index=True,
                use_container_width=True,
                height=600
            )








if __name__ == "__main__":
    main()