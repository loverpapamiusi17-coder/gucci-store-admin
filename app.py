import os, secrets, json
from datetime import datetime, timezone
from pathlib import Path
import requests
from flask import Flask, request, redirect, url_for, render_template, session, flash, jsonify, send_from_directory, abort
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename
from flask_wtf.csrf import CSRFProtect

BASE = Path(__file__).resolve().parent
UPLOAD_DIR = BASE / "static" / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
ALLOWED = {"png", "jpg", "jpeg", "webp", "gif"}

app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.environ.get("SECRET_KEY") or secrets.token_urlsafe(48),
    SQLALCHEMY_DATABASE_URI=os.environ.get("DATABASE_URL", f"sqlite:///{BASE / 'store.db'}"),
    SQLALCHEMY_TRACK_MODIFICATIONS=False,
    MAX_CONTENT_LENGTH=8 * 1024 * 1024,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE", "0") == "1",
    UPLOAD_FOLDER=str(UPLOAD_DIR),
)
db = SQLAlchemy(app)
csrf = CSRFProtect(app)

class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False)
    category = db.Column(db.String(40), nullable=False, default="Одежда")
    description = db.Column(db.Text, default="")
    price = db.Column(db.Integer, nullable=False, default=0)  # price in RUB kopecks
    image = db.Column(db.String(255), default="")
    stock = db.Column(db.Integer, nullable=False, default=0)
    active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

class Order(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    customer_name = db.Column(db.String(120), nullable=False)
    contact = db.Column(db.String(160), nullable=False)
    delivery = db.Column(db.String(300), nullable=False)
    comment = db.Column(db.Text, default="")
    items_json = db.Column(db.Text, nullable=False)
    total = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(30), nullable=False, default="Новый")
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

class Setting(db.Model):
    key = db.Column(db.String(80), primary_key=True)
    value = db.Column(db.Text, nullable=False, default="")

STATUSES = ["Новый", "Подтверждён", "Оплачен", "Отправлен", "Выполнен", "Отменён"]
CATEGORIES = ["Одежда", "Обувь", "Сумки", "Аксессуары", "Парфюм"]

def rub(kopecks):
    return f"{kopecks / 100:,.2f} ₽".replace(",", " ").replace(".", ",")

@app.template_filter("rub")
def rub_filter(kopecks): return rub(kopecks)

@app.before_request
def enforce_https_in_production():
    # Configure HTTPS at your hosting provider. Secure cookies are enabled with COOKIE_SECURE=1.
    pass

def logged_in():
    return bool(session.get("admin_ok"))

def admin_required():
    if not logged_in():
        return redirect(url_for("login", next=request.path))
    return None

@app.route("/admin/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        password = os.environ.get("ADMIN_PASSWORD", "")
        if not password:
            flash("Сначала задай ADMIN_PASSWORD в переменных окружения.", "error")
        elif secrets.compare_digest(request.form.get("password", ""), password):
            session.clear()
            session["admin_ok"] = True
            session["csrf_marker"] = secrets.token_urlsafe(24)
            return redirect(request.args.get("next") or url_for("dashboard"))
        else:
            flash("Неверный пароль.", "error")
    return render_template("login.html")

@app.post("/admin/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/")
def home():
    return redirect(url_for("dashboard") if logged_in() else url_for("login"))

@app.route("/admin")
def dashboard():
    r = admin_required()
    if r: return r
    return render_template("dashboard.html", products=Product.query.order_by(Product.id.desc()).all(),
                           orders=Order.query.order_by(Order.id.desc()).limit(10).all(),
                           product_count=Product.query.count(), order_count=Order.query.count(), statuses=STATUSES)

@app.route("/admin/products", methods=["GET", "POST"])
def products():
    r = admin_required()
    if r: return r
    if request.method == "POST":
        try:
            name = request.form.get("name", "").strip()
            category = request.form.get("category", "Одежда")
            price = round(float(request.form.get("price", "0").replace(",", ".")) * 100)
            stock = int(request.form.get("stock", "0"))
            if not name or len(name) > 160 or price < 0 or stock < 0 or category not in CATEGORIES:
                raise ValueError("Проверь название, категорию, цену и остаток.")
            image = ""
            file = request.files.get("image")
            if file and file.filename:
                filename = secure_filename(file.filename)
                ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
                if ext not in ALLOWED: raise ValueError("Фото: разрешены JPG, PNG, WEBP или GIF.")
                filename = secrets.token_hex(12) + "." + ext
                file.save(UPLOAD_DIR / filename)
                image = filename
            p = Product(name=name, category=category, description=request.form.get("description","")[:3000],
                        price=price, stock=stock, image=image, active=bool(request.form.get("active")))
            db.session.add(p); db.session.commit()
            flash("Товар добавлен.", "success")
        except (ValueError, TypeError) as e:
            flash(str(e) or "Проверьте поля товара.", "error")
        return redirect(url_for("products"))
    return render_template("products.html", products=Product.query.order_by(Product.id.desc()).all(), categories=CATEGORIES)

@app.post("/admin/products/<int:pid>/update")
def update_product(pid):
    r = admin_required()
    if r: return r
    p = db.get_or_404(Product, pid)
    try:
        p.name = request.form.get("name", p.name).strip()
        p.category = request.form.get("category", p.category)
        p.description = request.form.get("description", p.description)[:3000]
        p.price = round(float(request.form.get("price", str(p.price/100)).replace(",", "."))*100)
        p.stock = int(request.form.get("stock", p.stock))
        p.active = bool(request.form.get("active"))
        if not p.name or p.category not in CATEGORIES or p.price < 0 or p.stock < 0: raise ValueError()
        file = request.files.get("image")
        if file and file.filename:
            filename = secure_filename(file.filename)
            ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
            if ext not in ALLOWED: raise ValueError()
            filename = secrets.token_hex(12) + "." + ext
            file.save(UPLOAD_DIR / filename); p.image = filename
        db.session.commit(); flash("Изменения сохранены.", "success")
    except (ValueError, TypeError):
        db.session.rollback(); flash("Проверьте поля и формат фото.", "error")
    return redirect(url_for("products"))

@app.post("/admin/products/<int:pid>/delete")
def delete_product(pid):
    r = admin_required()
    if r: return r
    p = db.get_or_404(Product, pid)
    db.session.delete(p); db.session.commit()
    flash("Товар удалён.", "success")
    return redirect(url_for("products"))

@app.route("/admin/orders")
def orders():
    r = admin_required()
    if r: return r
    return render_template("orders.html", orders=Order.query.order_by(Order.id.desc()).all(), statuses=STATUSES)

@app.post("/admin/orders/<int:oid>/status")
def update_order_status(oid):
    r = admin_required()
    if r: return r
    order = db.get_or_404(Order, oid)
    status = request.form.get("status")
    if status not in STATUSES: abort(400)
    order.status = status; db.session.commit()
    flash(f"Заказ #{oid}: статус обновлён.", "success")
    return redirect(url_for("orders"))

@app.route("/admin/settings", methods=["GET", "POST"])
def settings():
    r = admin_required()
    if r: return r
    keys = ["shop_name", "currency", "delivery_text", "checkout_fields", "manager_username"]
    if request.method == "POST":
        for key in keys:
            value = request.form.get(key, "").strip()
            row = db.session.get(Setting, key)
            if row is None: row = Setting(key=key, value=value); db.session.add(row)
            else: row.value = value
        db.session.commit(); flash("Настройки сохранены.", "success")
        return redirect(url_for("settings"))
    vals = {s.key:s.value for s in Setting.query.filter(Setting.key.in_(keys)).all()}
    vals.setdefault("shop_name", "Gucci Store"); vals.setdefault("currency", "RUB")
    vals.setdefault("delivery_text", "Доставка согласовывается с менеджером.")
    vals.setdefault("checkout_fields", "Имя, Контакт, Адрес или способ доставки")
    vals.setdefault("manager_username", "")
    return render_template("settings.html", values=vals)

@app.get("/api/products")
def api_products():
    rows = Product.query.filter_by(active=True).order_by(Product.id.desc()).all()
    return jsonify([{"id":p.id,"name":p.name,"category":p.category,"description":p.description,
                     "price":p.price/100,"currency":"RUB","image":url_for("uploaded_file", filename=p.image, _external=True) if p.image else None,
                     "stock":p.stock} for p in rows])

@app.post("/api/orders")
def api_create_order():
    # Public endpoint: validate everything server-side; add rate limiting/WAF at deployment.
    data = request.get_json(silent=True) or {}
    name = str(data.get("name","")).strip()[:120]
    contact = str(data.get("contact","")).strip()[:160]
    delivery = str(data.get("delivery","")).strip()[:300]
    comment = str(data.get("comment","")).strip()[:1000]
    raw_items = data.get("items", [])
    if not name or not contact or not delivery or not isinstance(raw_items, list) or not raw_items or len(raw_items)>50:
        return jsonify(error="Заполните имя, контакт, доставку и товары."), 400
    lines=[]; total=0
    for item in raw_items:
        try: pid=int(item.get("product_id")); qty=int(item.get("quantity"))
        except (ValueError, TypeError, AttributeError): return jsonify(error="Некорректный состав заказа."), 400
        if qty<1 or qty>50: return jsonify(error="Некорректное количество."), 400
        p=Product.query.filter_by(id=pid, active=True).first()
        if not p or p.stock < qty: return jsonify(error="Товар недоступен или недостаточно остатка."), 409
        lines.append({"product_id":p.id,"name":p.name,"quantity":qty,"unit_price":p.price})
        total += p.price*qty
    order=Order(customer_name=name, contact=contact, delivery=delivery, comment=comment,
                items_json=json.dumps(lines, ensure_ascii=False), total=total)
    for line in lines:
        p=db.session.get(Product, line["product_id"]); p.stock -= line["quantity"]
    db.session.add(order); db.session.commit()
    notify_telegram(order, lines)
    return jsonify(ok=True, order_id=order.id), 201

def notify_telegram(order, lines):
    token=os.environ.get("TELEGRAM_BOT_TOKEN","")
    chat_id=os.environ.get("ADMIN_CHAT_ID","")
    if not token or not chat_id: return
    products_text="\n".join(f"• {x['name']} × {x['quantity']}" for x in lines)
    text_msg=(f"🛍 Новый заказ Gucci Store #{order.id}\nИмя: {order.customer_name}\n"
              f"Контакт: {order.contact}\nДоставка: {order.delivery}\n{products_text}\n"
              f"Итого: {rub(order.total)}\nКомментарий: {order.comment or '—'}")
    try: requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                       json={"chat_id":chat_id,"text":text_msg}, timeout=5).raise_for_status()
    except requests.RequestException: app.logger.exception("Telegram notification failed")

@app.get("/uploads/<path:filename>")
def uploaded_file(filename):
    return send_from_directory(UPLOAD_DIR, filename)

with app.app_context():
    db.create_all()
    defaults={"shop_name":"Gucci Store","currency":"RUB","delivery_text":"Доставка согласовывается с менеджером.",
              "checkout_fields":"Имя, Контакт, Адрес или способ доставки","manager_username":""}
    for k,v in defaults.items():
        if not db.session.get(Setting,k): db.session.add(Setting(key=k,value=v))
    db.session.commit()

if __name__ == "__main__":
    # Local development only; use gunicorn/production server behind HTTPS in deployment.
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "5000")), debug=False)
