"""Trip validation and money calculations. No floats, eval, or network services."""
import ast
import re
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext

CATEGORIES = {'tickets': 'Билеты', 'hotel': 'Проживание', 'daily': 'Суточные', 'taxi': 'Такси', 'other': 'Прочие расходы'}
CENT = Decimal('0.01')

def calculate(expression):
    source = str(expression).strip().replace(',', '.').replace(' ', '').replace('\u00a0', '').replace('×', '*').replace('÷', '/')
    if not source:
        return Decimal('0.00')
    if len(source) > 180 or not re.fullmatch(r'[0-9.+*/()\-]+', source):
        raise ValueError('В сумме допустимы числа, скобки и знаки + - * /.')
    try:
        tree = ast.parse(source, mode='eval')
        if sum(1 for _ in ast.walk(tree)) > 100:
            raise ValueError('Слишком длинное выражение.')
        def visit(node):
            if isinstance(node, ast.Constant) and type(node.value) in (int, float):
                return Decimal(ast.get_source_segment(source, node))
            if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
                return visit(node.operand) * (-1 if isinstance(node.op, ast.USub) else 1)
            if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)):
                a, b = visit(node.left), visit(node.right)
                if isinstance(node.op, ast.Add): result = a + b
                elif isinstance(node.op, ast.Sub): result = a - b
                elif isinstance(node.op, ast.Mult): result = a * b
                else: result = a / b
                if abs(result) > Decimal('999999999999'):
                    raise ValueError('Слишком большая сумма.')
                return result
            raise ValueError('Недопустимое выражение.')
        with localcontext() as ctx:
            ctx.prec = 40
            value = visit(tree.body).quantize(CENT, rounding=ROUND_HALF_UP)
        if value < 0 or value > Decimal('999999999.99'):
            raise ValueError('Сумма должна быть от 0 до 999 999 999,99 руб.')
        return value
    except (SyntaxError, InvalidOperation, ArithmeticError, RecursionError):
        raise ValueError('Не удалось посчитать сумму. Проверьте выражение и деление на ноль.') from None

def money(value):
    return f'{Decimal(value):,.2f}'.replace(',', ' ').replace('.', ',')

def text(value, limit=500):
    if not isinstance(value, str) or len(value) > limit or any(ord(c) < 32 and c not in '\r\n\t' for c in value):
        raise ValueError(f'Текстовое поле: максимум {limit} символов.')
    return value.strip()

def default_trip():
    today = date.today().isoformat()
    return dict(name='', city='', start=today, end=today, document_date=today,
        report_date='', memo_date='',
        organization='ООО «Пример»', recipient_title='Генеральному директору',
        recipient='Петровой А.А.', role='инженера-программиста',
        employee='Иванов И.И.', employee_genitive='Иванова И.И.', employee_dative='Иванову И.И.',
        purpose='участия в партнерской конференции', issued='0',
        planned={k:'0' for k in CATEGORIES}, expenses=[],
        memo_amount='0', memo_purpose='покупки расходных материалов для технического отдела',
        memo_text='', rks='', vov='', pks='', report_copies=2,
        include_request=True, include_report=True, include_memo=False, include_details=False,
        issued_from_plan=True, daily_from_plan=True)

def apply_plan_defaults(trip):
    if trip.get('issued_from_plan', False):
        trip['issued'] = str(sum((calculate(v) for v in trip['planned'].values()), Decimal('0.00')))
    if trip.get('daily_from_plan', False):
        daily = next((r for r in trip['expenses'] if r.get('quick') and r['category']=='daily'), None)
        if daily is None:
            daily = dict(category='daily', quick=True, date='', description='Суточные по заявке', receipt='')
            trip['expenses'].append(daily)
        daily['amount'] = trip['planned']['daily']
        daily['value'] = str(calculate(daily['amount']))
    return trip

def normalize(data):
    if not isinstance(data, dict):
        raise ValueError('Ожидалась карточка командировки.')
    result = default_trip()
    for key in ('issued_from_plan','daily_from_plan'):
        result[key]=bool(data.get(key,result[key]))
    for key, default in result.items():
        if isinstance(default, str):
            result[key] = text(data.get(key, default), 5000 if key == 'memo_text' else 500)
    for key in ('start', 'end', 'document_date', 'report_date', 'memo_date'):
        if key in ('report_date', 'memo_date') and not result[key]: continue
        try: date.fromisoformat(result[key])
        except ValueError: raise ValueError('Укажите корректные даты.') from None
    if result['end'] < result['start']:
        raise ValueError('Дата окончания раньше даты начала.')
    for key in ('city', 'employee', 'employee_genitive', 'employee_dative', 'recipient', 'organization'):
        if not result[key]: raise ValueError('Заполните город, организацию, получателя и ФИО сотрудника во всех падежах.')
    for key in ('issued', 'memo_amount'):
        if key=='issued' and result['issued_from_plan']: continue
        calculate(result[key])
    planned = data.get('planned', {})
    if not isinstance(planned, dict): raise ValueError('Неверные плановые суммы.')
    result['planned'] = {k: text(str(planned.get(k, '0')), 180) for k in CATEGORIES}
    for value in result['planned'].values(): calculate(value)
    expenses = data.get('expenses', [])
    if not isinstance(expenses, list) or len(expenses) > 1000:
        raise ValueError('Допускается не более 1000 расходов.')
    result['expenses'] = []
    for expense in expenses:
        if not isinstance(expense, dict): raise ValueError('Неверная строка расходов.')
        category = expense.get('category', 'other')
        if category not in CATEGORIES: raise ValueError('Неизвестный вид расхода.')
        row = {k:text(str(expense.get(k, '')), 180 if k == 'amount' else 500) for k in ('date', 'description', 'amount', 'receipt')}
        if result['daily_from_plan'] and category=='daily' and expense.get('quick'):
            row['amount']=result['planned']['daily']
        if row['date']:
            try: date.fromisoformat(row['date'])
            except ValueError: raise ValueError('Некорректная дата расхода.') from None
        row.update(category=category, value=str(calculate(row['amount'])), quick=bool(expense.get('quick',False)))
        result['expenses'].append(row)
    for key in ('include_request', 'include_report', 'include_memo', 'include_details', 'issued_from_plan', 'daily_from_plan'):
        result[key] = bool(data.get(key, result[key]))
    try: copies = int(data.get('report_copies', 2))
    except (TypeError, ValueError): raise ValueError('Число экземпляров должно быть от 1 до 5.') from None
    if not 1 <= copies <= 5: raise ValueError('Число экземпляров должно быть от 1 до 5.')
    result['report_copies'] = copies
    return apply_plan_defaults(result)

def totals(trip):
    by_category = {k: Decimal('0.00') for k in CATEGORIES}
    for row in trip['expenses']:
        by_category[row['category']] += calculate(row['amount'])
    spent = sum(by_category.values(), Decimal('0.00'))
    issued = calculate(trip['issued'])
    balance = issued - spent
    return dict(categories={k:str(v) for k,v in by_category.items()}, spent=str(spent),
        issued=str(issued), refund=str(max(balance, Decimal(0))),
        overrun=str(max(-balance, Decimal(0))),
        planned=str(sum((calculate(v) for v in trip['planned'].values()), Decimal('0.00'))))
