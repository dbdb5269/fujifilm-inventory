import os
import requests
import urllib.parse
from datetime import datetime
from flask import Flask, request, jsonify, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from sqlalchemy.exc import IntegrityError

app = Flask(__name__, static_folder='.')

# 数据库配置
db_path = os.environ.get('DB_PATH', 'fujifilm.db')
app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
CORS(app)


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
            'id': self.id,
            'name': self.name,
            'type': self.type,
            'image': self.image_url,
            'originalPrice': float(self.original_price or 0),
            'marketPrice': float(self.market_price or 0)
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
        delta_days = (self.expiry_date - today).days
        status = 'normal'
        if delta_days < 0:
            status = 'expired'
        elif delta_days <= 90:
            status = 'urgent'
        elif delta_days <= 180:
            status = 'warning'

        return {
            'id': self.id,
            'name': self.name,
            'type': self.type,
            'quantity': self.quantity,
            'expiryDate': self.expiry_date.strftime('%Y-%m-%d'),
            'originalPrice': float(self.original_price or 0),
            'marketPrice': float(self.market_price or 0),
            'image': self.image_url,
            'status': status,
            'daysLeft': delta_days
        }


# [新增] 系统配置表 (用于存储 Bark 服务器地址)
class SystemConfig(db.Model):
    __tablename__ = 'system_config'
    key = db.Column(db.String(50), primary_key=True)
    value = db.Column(db.String(255))


# [新增] Bark Token 表
class BarkToken(db.Model):
    __tablename__ = 'bark_tokens'
    id = db.Column(db.Integer, primary_key=True)
    remark = db.Column(db.String(50), default='My Device')
    token = db.Column(db.String(100), nullable=False, unique=True)

    def to_dict(self):
        return {'id': self.id, 'remark': self.remark, 'token': self.token}


# --- 路由 ---

@app.route('/')
def index():
    return send_from_directory('.', 'polaroid_inventory_api.html')


# === 产品与库存 API (保持不变) ===
# 为了节省篇幅，这里保留原有的 get_products, add_product 等所有产品和库存相关的 API 代码。
# 请确保之前生成的 inventory/products 相关路由都在这里。

@app.route('/api/products', methods=['GET'])
def get_products():
    query = Product.query
    type_filter = request.args.get('type')
    if type_filter and type_filter != 'all':
        query = query.filter_by(type=type_filter)
    search_query = request.args.get('q')
    if search_query:
        query = query.filter(Product.name.ilike(f'%{search_query}%'))
    products = query.order_by(Product.name).all()
    return jsonify([p.to_dict() for p in products])


@app.route('/api/products', methods=['POST'])
def add_product():
    data = request.json
    try:
        new_prod = Product(
            name=data['name'],
            type=data['type'],
            image_url=data.get('image', ''),
            original_price=data.get('originalPrice', 0),
            market_price=data.get('marketPrice', 0)
        )
        db.session.add(new_prod)
        db.session.commit()
        return jsonify(new_prod.to_dict()), 201
    except IntegrityError:
        db.session.rollback()
        return jsonify({'error': '该名称的产品已存在'}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/products/<int:prod_id>', methods=['PUT'])
def update_product(prod_id):
    data = request.json
    try:
        prod = Product.query.get(prod_id)
        if not prod: return jsonify({'error': 'Not found'}), 404
        if 'name' in data: prod.name = data['name']
        if 'type' in data: prod.type = data['type']
        if 'image' in data: prod.image_url = data['image']
        if 'originalPrice' in data: prod.original_price = data['originalPrice']
        if 'marketPrice' in data: prod.market_price = data['marketPrice']
        db.session.commit()
        return jsonify(prod.to_dict())
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/products/<int:prod_id>', methods=['DELETE'])
def delete_product(prod_id):
    prod = Product.query.get(prod_id)
    if prod:
        db.session.delete(prod)
        db.session.commit()
    return jsonify({'message': 'Deleted'})


@app.route('/api/inventory', methods=['GET'])
def get_inventory():
    items = Inventory.query.order_by(Inventory.name, Inventory.expiry_date).all()
    return jsonify([item.to_dict() for item in items])


@app.route('/api/inventory', methods=['POST'])
def add_inventory_item():
    data = request.json
    try:
        expiry_dt = datetime.strptime(data['expiryDate'], '%Y-%m-%d').date()
        existing = Inventory.query.filter_by(name=data['name'], type=data['type'], expiry_date=expiry_dt,
                                             original_price=data.get('originalPrice', 0)).first()
        if existing:
            existing.quantity += data['quantity']
            if not existing.image_url and data.get('image'): existing.image_url = data['image']
            if 'marketPrice' in data: existing.market_price = data['marketPrice']
            db.session.commit()
            return jsonify(existing.to_dict()), 200
        else:
            new_item = Inventory(name=data['name'], type=data['type'], quantity=data['quantity'], expiry_date=expiry_dt,
                                 original_price=data.get('originalPrice', 0), market_price=data.get('marketPrice', 0),
                                 image_url=data.get('image', ''))
            db.session.add(new_item)
            db.session.commit()
            return jsonify(new_item.to_dict()), 201
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/inventory/<int:item_id>/quantity', methods=['PUT'])
def update_stock(item_id):
    data = request.json
    item = Inventory.query.get(item_id)
    if item:
        item.quantity = max(0, item.quantity + data.get('change', 0))
        db.session.commit()
        return jsonify(item.to_dict())
    return jsonify({'error': 'Not found'}), 404


@app.route('/api/inventory/<int:item_id>', methods=['DELETE'])
def delete_inventory(item_id):
    item = Inventory.query.get(item_id)
    if item:
        db.session.delete(item)
        db.session.commit()
    return jsonify({'message': 'Deleted'})


# === [新增] 通知配置 API ===

@app.route('/api/settings/bark', methods=['GET', 'POST'])
def handle_bark_server():
    if request.method == 'GET':
        conf = SystemConfig.query.get('bark_server_url')
        return jsonify({'url': conf.value if conf else 'https://api.day.app'})

    # POST
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
    if request.method == 'GET':
        tokens = BarkToken.query.all()
        return jsonify([t.to_dict() for t in tokens])

    # POST
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
    if t:
        db.session.delete(t)
        db.session.commit()
    return jsonify({'message': 'Deleted'})


# === [新增] 触发通知逻辑 ===

@app.route('/api/notify', methods=['POST'])
def trigger_notification():
    # 1. 扫描库存
    items = Inventory.query.all()
    today = datetime.now().date()

    expired = []
    urgent = []  # < 90天
    warning = []  # < 180天

    for item in items:
        # 只有库存 > 0 才统计
        if item.quantity <= 0: continue

        days = (item.expiry_date - today).days
        info = f"{item.name} ({item.type}) x{item.quantity} [到期:{item.expiry_date}]"

        if days < 0:
            expired.append(info)
        elif days <= 90:
            urgent.append(info)
        elif days <= 180:
            warning.append(info)

    # 2. 如果没有任何预警，直接返回
    if not (expired or urgent or warning):
        return jsonify({'message': '无预警信息，无需发送'}), 200

    # 3. 构建消息体
    title = "拍立得库存预警"
    body_lines = []

    if expired:
        body_lines.append(f"🔴 已过期 ({len(expired)}):")
        body_lines.extend([f" - {x}" for x in expired])
        body_lines.append("")  # 空行

    if urgent:
        body_lines.append(f"🟠 临期<3月 ({len(urgent)}):")
        body_lines.extend([f" - {x}" for x in urgent])
        body_lines.append("")

    if warning:
        body_lines.append(f"🟡 预警<6月 ({len(warning)}):")
        body_lines.extend([f" - {x}" for x in warning])

    body_content = "\n".join(body_lines)

    # 4. 获取配置
    conf = SystemConfig.query.get('bark_server_url')
    base_url = conf.value.rstrip('/') if conf else 'https://api.day.app'
    tokens = BarkToken.query.all()

    if not tokens:
        return jsonify({'error': '未配置 Bark Token'}), 400

    # 5. 发送请求 (使用 GET 方式: /token/title/body)
    # 注意：URL 内容需要编码
    success_count = 0
    safe_title = urllib.parse.quote(title)
    safe_body = urllib.parse.quote(body_content)

    for t in tokens:
        try:
            # 构造 URL: https://server/token/title/body
            url = f"{base_url}/{t.token}/{safe_title}/{safe_body}"
            # 增加 group 参数以便在手机上分组显示
            url += "?group=PolaroidInventory"

            resp = requests.get(url, timeout=5)
            if resp.status_code == 200:
                success_count += 1
        except Exception as e:
            print(f"Failed to send to {t.remark}: {e}")

    return jsonify({
        'message': f'发送完成',
        'details': f'成功推送 {success_count}/{len(tokens)} 个设备',
        'stats': {'expired': len(expired), 'urgent': len(urgent), 'warning': len(warning)}
    })


def init_db():
    with app.app_context():
        db.create_all()
        # 预置数据略...


if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', port=50001, debug=True)