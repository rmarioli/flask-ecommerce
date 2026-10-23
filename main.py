from __future__ import annotations
from flask import Flask, abort, render_template, redirect, url_for, flash, request
from flask_bootstrap import Bootstrap5
from flask_ckeditor import CKEditor
from flask_wtf import FlaskForm
from wtforms import StringField, SubmitField, PasswordField
from wtforms.validators import DataRequired
from flask_login import UserMixin, login_user, LoginManager, current_user, logout_user, login_required
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import relationship, DeclarativeBase, Mapped, mapped_column, joinedload
from sqlalchemy import Integer, String, Text, ForeignKey, or_
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
import stripe
import os
from dotenv import load_dotenv


load_dotenv()
app = Flask(__name__)
app.secret_key = os.getenv("KEY")
ckeditor = CKEditor(app)
Bootstrap5(app)


# CREATE DATABASE
class Base(DeclarativeBase):
    pass

stripe.api_key = os.getenv("KEY_PAYMENT")

app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv("SQL_DB")
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(model_class=Base)
db.init_app(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"
login_manager.login_message = "Please log in to access this page."


# CONFIGURE TABLES
class Products(db.Model):
    __tablename__ = "products"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(250), nullable=False)
    price: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(String(250), nullable=False)
    img_url: Mapped[str] = mapped_column(String(250), nullable=False)
    cart_items: Mapped[list["UserCart"]] = relationship("UserCart", back_populates="product")


class User(UserMixin, db.Model):
    __tablename__ = "user_registered"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(250), unique=True, nullable=False)
    password: Mapped[str] = mapped_column(String(250), nullable=False)
    name: Mapped[str] = mapped_column(String(250), nullable=False)
    # Relationship to cart items
    cart_items: Mapped[list["UserCart"]] = relationship("UserCart", back_populates="user")

    def set_password(self, password):
        self.password = generate_password_hash(password, method='pbkdf2:sha256', salt_length=8)
    def check_password(self, password):
        return check_password_hash(self.password, password)


class UserCart(db.Model):
    __tablename__ = "user_carts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    amount: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # Foreign keys
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("user_registered.id"), nullable=False)
    product_id: Mapped[int] = mapped_column(Integer, ForeignKey("products.id"), nullable=False)
    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="cart_items")
    product: Mapped["Products"] = relationship("Products", back_populates="cart_items")


#Create a RegisterForm to register new users
class RegisterForm(FlaskForm):
    email = StringField("Email", validators=[DataRequired()])
    password = PasswordField("Password", validators=[DataRequired()])
    name = StringField("Name", validators=[DataRequired()])
    submit = SubmitField("Sign in")

#Create a LoginForm to login existing users
class LoginForm(FlaskForm):
    email = StringField("Email", validators=[DataRequired()])
    password = PasswordField("Password", validators=[DataRequired()])
    submit = SubmitField("Log in")


with app.app_context():
    db.create_all()

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


#============================================= ROUTES ======================================================
@app.context_processor
def inject_user():
    return {
        'logged_in': current_user.is_authenticated,
        'current_user': current_user
    }

@app.context_processor
def inject_cart_data():
    if current_user.is_authenticated:
        cart_items = UserCart.query.filter_by(
            user_id=current_user.id
        ).all()

        cart_count = sum(item.amount for item in cart_items)
        cart_total = sum(item.amount*item.product.price for item in cart_items)
    else:
        cart_items = []
        cart_count = 0
        cart_total = 0

    return {
        "cart_items": cart_items,
        "cart_count": cart_count,
        "cart_total": cart_total
    }


def admin_only(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # If user is not authenticated OR user id is not 1 (admin)
        if not current_user.is_authenticated or current_user.id != 1:
            flash('Access denied. Admin privileges required.', 'danger')
            return abort(403)
        return f(*args, **kwargs)
    return decorated_function

@app.route('/')
def home():
    item = Products.query.filter(Products.id == 1).first()
    products = Products.query.filter(
        or_(
            Products.name.ilike("%1%"),
            Products.name.ilike("%2%"),
            Products.name.ilike("%3%"),
            Products.name.ilike("%4%"),
        )
    ).all()
    user_id = current_user.id if current_user.is_authenticated else None
    electronics_list = Products.query.filter_by(category="Electronics").all()
    return render_template("index.html", all_products=products, all_electr=electronics_list, userr=user_id, product=item)

@app.route('/grid/<cat>')
def grid_prod(cat):
    products_list = Products.query.filter_by(category=cat).all()
    return render_template("product_grids.html", all_products=products_list, category=cat)

@app.route('/grid/search')
def search():
    query = request.args.get('search_bar')
    products_list = Products.query.filter(Products.name.ilike(f"%{query}%")).all()
    return render_template("product_grids.html", all_products=products_list, category="Search result")


@app.route('/product/<prod_id>')
def product(prod_id):
    item = Products.query.filter(Products.id == prod_id).first()
    products_list = Products.query.filter_by(category=item.category).all()
    return render_template("product.html", product=item, list_show=products_list)


@app.route('/add_cart/<int:prod_id>', methods=['POST'])
@login_required
def add_cart(prod_id):
    amount = request.form.get('amount', 1)
    product_add = Products.query.get(prod_id)
    cart_item = UserCart.query.filter_by(user_id=current_user.id, product_id=prod_id).first()

    if cart_item:
        cart_item.amount += int(amount)
    else:
        cart_item = UserCart(
            user_id=current_user.id,
            product_id=prod_id,
            amount=int(amount)
        )
        db.session.add(cart_item)

    db.session.commit()
    return redirect(url_for("home"))


@app.route('/add_subs_qty/<int:cart_id>/<int:add_subs>', methods=["GET", "POST"])
def add_subs_qty(cart_id, add_subs):
    cart_item = UserCart.query.filter_by(id=cart_id).first()

    if add_subs == 0:
        cart_item.amount += 1
    else:
        if cart_item.amount == 1:
            db.session.delete(cart_item)
        else:
            cart_item.amount -= 1

    db.session.commit()
    return redirect(url_for("home"))


@app.route('/pay', methods=['POST'])
def pay():
    cart_items = UserCart.query.filter_by(user_id=current_user.id).all()
    line_items = []
    for item in cart_items:
        line_items.append({
            "price_data": {
                "currency": "usd",
                "product_data": {
                    "name": item.product.name,
                },
                "unit_amount": int(item.product.price * 100),  # cents
            },
            "quantity": item.amount,
        })

    session = stripe.checkout.Session.create(
        payment_method_types=["card"],
        line_items=line_items,
        mode="payment",
        success_url=url_for("success", _external=True),
        cancel_url=url_for("cancel", _external=True),
    )
    return redirect(session.url, code=303)


@app.route("/success")
def success():
    return '<h1 style="text-align: center"> Hello world! </h1>'


@app.route("/cancel")
def cancel():
    return redirect(url_for("home"))


@app.route('/register', methods=["GET", "POST"])
def register():
    form = RegisterForm()
    if form.validate_on_submit():
        user = User.query.filter_by(email=form.email.data).first()
        if user:
            flash('Email already exists')
            return redirect(url_for('register'))

        new_user = User(
            email=form.email.data,
            name=form.name.data
        )
        new_user.set_password(form.password.data)
        db.session.add(new_user)
        db.session.commit()
        login_user(new_user, remember=True)
        return redirect(url_for("home"))
    return render_template("register.html", form=form)


# Retrieve a user from the database based on their email.
@app.route('/login', methods=["GET", "POST"])
def login():
    form = LoginForm()
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        remember = request.form.get('remember') == 'on'

        user = User.query.filter_by(email=email).first()

        if not user:
            # Email does not exist
            flash('Email does not exists')
            return redirect(url_for('login'))

        if user.check_password(password):
            login_user(user, remember=remember)
            return redirect(url_for('home'))
        else:
            flash('Invalid email or password')
            return redirect(url_for('login'))
    return render_template("login.html", form=form)


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('home'))


if __name__ == "__main__":
    app.run(debug=True, port=5002)
