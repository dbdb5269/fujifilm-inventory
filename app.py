import os
import uuid
import json
import requests
import urllib.parse
from datetime import datetime, date, timedelta
from flask import Flask, request, jsonify, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from sqlalchemy.exc import IntegrityError
from werkzeug.utils import secure_filename

app = Flask(__name__, static_folder='.')

# --- 基础路径配置 ---
basedir = os.path.abspath(os.path.dirname(__file__))

# 1. 数据库配置
db_path = os.environ.get('DB_PATH', os.path.join(basedir, 'data', 'fujifilm.db'))
db_dir = os.path.dirname(db_path)
if db_dir and not os.path.exists(db_dir):
    os.makedirs(db_dir, exist_ok=True)

app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# 2. 上传文件配置
# [修正] 默认路径改为 db_dir 下的 uploads，确保所有数据都在 data 目录内
UPLOAD_FOLDER = os.environ.get('UPLOAD_PATH', os.path.join(db_dir, 'uploads'))
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# 3. JSON 目录配置
JSON_CATALOG_PATH = os.environ.get('JSON_PATH', os.path.join(db_dir, 'products.json'))

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp', 'avif'}

db = SQLAlchemy(app)
CORS(app)


# --- 辅助函数 ---
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def save_image(file):
    if file and allowed_file(file.filename):
        ext = file.filename.rsplit('.', 1)[1].lower()
        filename = f"{uuid.uuid4().hex}.{ext}"
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
        return filename
    return None


def get_next_month_first_day(d):
    """获取给定日期下个月的第一天"""
    if d.month == 12:
        return date(d.year + 1, 1, 1)
    else:
        return date(d.year, d.month + 1, 1)


def sync_catalog_from_json():
    """从 JSON 文件同步产品库"""
    if not os.path.exists(JSON_CATALOG_PATH):
        # ... (保持创建示例文件的逻辑) ...
        return {"status": "skipped", "message": "JSON file not found"}

    try:
        with open(JSON_CATALOG_PATH, 'r', encoding='utf-8') as f:
            catalog = json.load(f)

        count_added = 0
        count_updated = 0

        for item in catalog:
            name = item.get('name')
            p_type = item.get('type')
            image = item.get('image')
            original_price = item.get('original_price')
            market_price = item.get('market_price')

            if not name or not p_type: continue

            product = Product.query.filter_by(name=name).first()
            if not product:
                new_prod = Product(
                    name=name, type=p_type, image_url=image,
                    original_price=original_price or 0, market_price=market_price or 0
                )
                db.session.add(new_prod)
                count_added += 1
            else:
                updated = False
                if product.type != p_type: product.type = p_type; updated = True
                if image and product.image_url != image: product.image_url = image; updated = True
                if original_price is not None and float(product.original_price or 0) != float(
                    original_price): product.original_price = original_price; updated = True
                if market_price is not None and float(product.market_price or 0) != float(
                    market_price): product.market_price = market_price; updated = True
                if updated: count_updated += 1

        db.session.commit()
        return {"status": "success", "message": f"同步完成: 新增 {count_added}, 更新 {count_updated}"}
    except Exception as e:
        db.session.rollback()
        return {"status": "error", "message": str(e)}


def save_products_to_json():
    """DB -> JSON"""
    try:
        products = Product.query.order_by(Product.id).all()
        data_list = []
        for p in products:
            data_list.append({
                "name": p.name, "type": p.type, "image": p.image_url,
                "original_price": float(p.original_price or 0), "market_price": float(p.market_price or 0)
            })
        with open(JSON_CATALOG_PATH, 'w', encoding='utf-8') as f:
            json.dump(data_list, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Error auto-saving products.json: {e}")


# --- 模型定义 ---
class Product(db.Model):
    __tablename__ = 'products'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False, unique=True)
    type = db.Column(db.String(10), nullable=False)
    image_url = db.Column(db.Text, nullable=True)
    original_price = db.Column(db.Numeric(10, 2), default=0.00)
    market_price = db.Column(db.Numeric(10, 2), default=0.00)

    def to_dict(self):
        return {
            'id': self.id, 'name': self.name, 'type': self.type, 'image': self.image_url,
            'originalPrice': float(self.original_price or 0), 'marketPrice': float(self.market_price or 0)
        }


class Inventory(db.Model):
    __tablename__ = 'inventory'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    type = db.Column(db.String(10), nullable=False)
    quantity = db.Column(db.Integer, default=0)
    expiry_date = db.Column(db.Date, nullable=False)
    original_price = db.Column(db.Numeric(10, 2), default=0.00)
    market_price = db.Column(db.Numeric(10, 2), default=0.00)
    image_url = db.Column(db.Text, nullable=True)

    def to_dict(self):
        today = datetime.now().date()

        # [修改] 过期计算逻辑：相纸过期是指 "Use before YYYY-MM"，意味着该月结束才算过期
        # 所以我们计算 "下个月1号" 与 "今天" 的差距
        # 如果今天是 12月15日，过期是 12月，则有效直到 1月1日。差距 > 0，未过期。
        valid_until = get_next_month_first_day(self.expiry_date)
        delta_days = (valid_until - today).days

        status = 'normal'
        if delta_days < 0:
            status = 'expired'
        elif delta_days <= 90:
            status = 'urgent'
        elif delta_days <= 180:
            status = 'warning'

        return {
            'id': self.id, 'name': self.name, 'type': self.type, 'quantity': self.quantity,
            # [修改] 返回前端只展示 YYYY-MM
            'expiryDate': self.expiry_date.strftime('%Y-%m'),
            'originalPrice': float(self.original_price or 0), 'marketPrice': float(self.market_price or 0),
            'image': self.image_url, 'status': status, 'daysLeft': delta_days
        }


class SystemConfig(db.Model):
    __tablename__ = 'system_config'
    key = db.Column(db.String(50), primary_key=True)
    value = db.Column(db.String(255))


class BarkToken(db.Model):
    __tablename__ = 'bark_tokens'
    id = db.Column(db.Integer, primary_key=True)
    remark = db.Column(db.String(50), default='My Device')
    token = db.Column(db.String(100), nullable=False, unique=True)

    def to_dict(self): return {'id': self.id, 'remark': self.remark, 'token': self.token}


# --- 路由 ---

@app.route('/')
def index():
    return send_from_directory('.', 'fujifilm_inventory_api.html')


@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)


@app.route('/api/products/sync', methods=['POST'])
def trigger_sync():
    result = sync_catalog_from_json()
    if result['status'] == 'error': return jsonify(result), 500
    return jsonify(result)


# === 产品库 API ===
@app.route('/api/products', methods=['GET'])
def get_products():
    # ... (保持不变) ...
    query = Product.query
    if request.args.get('type') and request.args.get('type') != 'all': query = query.filter_by(
        type=request.args.get('type'))
    if request.args.get('q'): query = query.filter(Product.name.ilike(f'%{request.args.get("q")}%'))
    return jsonify([p.to_dict() for p in query.order_by(Product.name).all()])


@app.route('/api/products', methods=['POST'])
def add_product():
    # ... (保持不变) ...
    data = request.json if request.is_json else request.form
    try:
        new_prod = Product(
            name=data.get('name'), type=data.get('type'), image_url=data.get('image'),
            original_price=data.get('originalPrice', 0), market_price=data.get('marketPrice', 0)
        )
        db.session.add(new_prod)
        db.session.commit()
        save_products_to_json()
        return jsonify(new_prod.to_dict()), 201
    except IntegrityError:
        db.session.rollback()
        return jsonify({'error': '该名称的产品已存在'}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/products/<int:prod_id>', methods=['PUT'])
def update_product(prod_id):
    # ... (保持不变) ...
    data = request.json if request.is_json else request.form
    try:
        prod = Product.query.get(prod_id)
        if not prod: return jsonify({'error': 'Not found'}), 404
        if 'name' in data: prod.name = data.get('name')
        if 'type' in data: prod.type = data.get('type')
        if 'originalPrice' in data: prod.original_price = data.get('originalPrice')
        if 'marketPrice' in data: prod.market_price = data.get('marketPrice')
        if 'image' in data: prod.image_url = data.get('image')
        db.session.commit()
        save_products_to_json()
        return jsonify(prod.to_dict())
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/products/<int:prod_id>', methods=['DELETE'])
def delete_product(prod_id):
    # ... (保持不变) ...
    prod = Product.query.get(prod_id)
    if prod:
        db.session.delete(prod)
        db.session.commit()
        save_products_to_json()
    return jsonify({'message': 'Deleted'})


# === 库存 API ===
@app.route('/api/inventory', methods=['GET'])
def get_inventory():
    items = Inventory.query.order_by(Inventory.name, Inventory.expiry_date).all()
    return jsonify([item.to_dict() for item in items])


@app.route('/api/inventory', methods=['POST'])
def add_inventory_item():
    data = request.json
    try:
        # [修改] 日期解析逻辑：支持 YYYY-MM
        expiry_str = data['expiryDate']
        if len(expiry_str) == 7:  # "2025-12"
            expiry_dt = datetime.strptime(expiry_str, '%Y-%m').date()
        else:
            expiry_dt = datetime.strptime(expiry_str, '%Y-%m-%d').date()

        # 始终确保存储为当月1号，方便统一管理
        expiry_dt = expiry_dt.replace(day=1)

        existing = Inventory.query.filter_by(
            name=data['name'], type=data['type'], expiry_date=expiry_dt, original_price=data.get('originalPrice', 0)
        ).first()

        if existing:
            existing.quantity += data['quantity']
            if data.get('image'): existing.image_url = data['image']
            if 'marketPrice' in data: existing.market_price = data['marketPrice']
            db.session.commit()
            return jsonify(existing.to_dict()), 200
        else:
            new_item = Inventory(
                name=data['name'], type=data['type'], quantity=data['quantity'], expiry_date=expiry_dt,
                original_price=data.get('originalPrice', 0), market_price=data.get('marketPrice', 0),
                image_url=data.get('image', '')
            )
            db.session.add(new_item)
            db.session.commit()
            return jsonify(new_item.to_dict()), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/inventory/<int:item_id>/quantity', methods=['PUT'])
def update_stock(item_id):
    # ... (保持不变) ...
    data = request.json
    item = Inventory.query.get(item_id)
    if item:
        item.quantity = max(0, item.quantity + data.get('change', 0))
        db.session.commit()
        return jsonify(item.to_dict())
    return jsonify({'error': 'Not found'}), 404


@app.route('/api/inventory/<int:item_id>', methods=['DELETE'])
def delete_inventory(item_id):
    # ... (保持不变) ...
    item = Inventory.query.get(item_id)
    if item:
        db.session.delete(item)
        db.session.commit()
    return jsonify({'message': 'Deleted'})


# === 通知配置 API (保持不变) ===
@app.route('/api/settings/bark', methods=['GET', 'POST'])
def handle_bark_server():
    if request.method == 'GET':
        conf = SystemConfig.query.get('bark_server_url')
        return jsonify({'url': conf.value if conf else 'https://api.day.app'})
    data = request.json
    conf = SystemConfig.query.get('bark_server_url')
    if not conf:
        conf = SystemConfig(key='bark_server_url', value=data['url'])
        db.session.add(conf)
    else:
        conf.value = data['url']
    db.session.commit()
    return jsonify({'message': 'Saved'})


@app.route('/api/settings/tokens', methods=['GET', 'POST'])
def handle_tokens():
    if request.method == 'GET': return jsonify([t.to_dict() for t in BarkToken.query.all()])
    data = request.json
    try:
        new_token = BarkToken(remark=data.get('remark', 'Device'), token=data['token'])
        db.session.add(new_token)
        db.session.commit()
        return jsonify(new_token.to_dict()), 201
    except IntegrityError:
        return jsonify({'error': 'Token 已存在'}), 400


@app.route('/api/settings/tokens/<int:tid>', methods=['DELETE'])
def delete_token(tid):
    t = BarkToken.query.get(tid)
    if t: db.session.delete(t); db.session.commit()
    return jsonify({'message': 'Deleted'})


# === 通知逻辑 (更新过期计算) ===
@app.route('/api/notify', methods=['POST'])
def trigger_notification():
    items = Inventory.query.all()
    today = datetime.now().date()
    expired, urgent, warning = [], [], []
    for item in items:
        if item.quantity <= 0: continue

        # [修改] 使用统一的月度过期计算函数
        valid_until = get_next_month_first_day(item.expiry_date)
        days = (valid_until - today).days

        # 显示格式调整为 YYYY-MM
        expiry_str = item.expiry_date.strftime('%Y-%m')
        info = f"{item.name} ({item.type}) x{item.quantity} [到期:{expiry_str}]"

        if days < 0:
            expired.append(info)
        elif days <= 90:
            urgent.append(info)
        elif days <= 180:
            warning.append(info)

    if not (expired or urgent or warning): return jsonify({'message': '无预警信息'}), 200

    title = "Fujifilm库存预警"
    body_lines = []
    if expired: body_lines.extend([f"🔴 已过期 ({len(expired)}):"] + [f" - {x}" for x in expired] + [""])
    if urgent: body_lines.extend([f"🟠 临期<3月 ({len(urgent)}):"] + [f" - {x}" for x in urgent] + [""])
    if warning: body_lines.extend([f"🟡 预警<6月 ({len(warning)}):"] + [f" - {x}" for x in warning])
    body_content = "\n".join(body_lines)

    conf = SystemConfig.query.get('bark_server_url')
    base_url = conf.value.rstrip('/') if conf else 'https://api.day.app'
    tokens = BarkToken.query.all()
    if not tokens: return jsonify({'error': '未配置 Bark Token'}), 400

    success_count = 0
    safe_title = urllib.parse.quote(title)
    safe_body = urllib.parse.quote(body_content)
    for t in tokens:
        try:
            url = f"{base_url}/{t.token}/{safe_title}/{safe_body}?group=FujifilmInventory"
            resp = requests.get(url, timeout=5)
            if resp.status_code == 200: success_count += 1
        except Exception:
            pass
    return jsonify({'message': '发送完成', 'details': f'成功推送 {success_count}/{len(tokens)} 个设备'})


def init_db():
    with app.app_context():
        db.create_all()
        sync_catalog_from_json()


if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', port=5000, debug=True)