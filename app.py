import os

from cs50 import SQL
from flask import Flask, flash, redirect, render_template, request, session
from flask_session import Session
from werkzeug.security import check_password_hash, generate_password_hash

from helpers import apology, login_required, lookup, usd

# Configure application
app = Flask(__name__)

# Custom filter
app.jinja_env.filters["usd"] = usd

# Configure session to use filesystem (instead of signed cookies)
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

# Configure CS50 Library to use SQLite database
db = SQL("sqlite:///finance.db")


@app.after_request
def after_request(response):
    """Ensure responses aren't cached"""
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Expires"] = 0
    response.headers["Pragma"] = "no-cache"
    return response


db.execute("""
    CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        symbol TEXT,
        shares INTEGER,
        price REAL,
        time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(id)
    )
""")


@app.route("/")
@login_required
def index():
    """Show portfolio of stocks"""
    user_id = session["user_id"]

    # Query for the user's cash balance
    cash = db.execute("SELECT cash FROM users WHERE id = ?", user_id)[0]["cash"]

    # Query for the user's stocks (symbol, shares, price, total value)
    portfolio = db.execute("""
        SELECT symbol, SUM(shares) AS shares, price
        FROM transactions
        WHERE user_id = ?
        GROUP BY symbol
    """, user_id)

    # For each stock in the portfolio, look up its current price
    total_stock_value = 0  # Variable to hold total value of all stocks
    for stock in portfolio:
        quote = lookup(stock["symbol"])
        stock["price"] = quote["price"] if quote else 0  # Lookup price
        stock["total"] = stock["shares"] * stock["price"]  # Total value of the stock
        total_stock_value += stock["total"]  # Add stock value to total

    # Calculate the total portfolio value (cash + stock value)
    total_value = cash + total_stock_value

    return render_template("index.html", portfolio=portfolio, cash=cash, total_value=total_value)


@app.route("/buy", methods=["GET", "POST"])
@login_required
def buy():
    """Buy shares of stock"""
    if request.method == "POST":
        # Ensure stock symbol was submitted
        symbol = request.form.get("symbol")
        if not symbol:
            return apology("must provide stock symbol", 400)

        # Look up stock quote
        quote = lookup(symbol)
        if not quote:
            return apology("invalid symbol", 400)

        # Ensure number of shares was submitted and is valid
        shares = request.form.get("shares")
        if not shares or not shares.isdigit() or int(shares) <= 0:
            return apology("must provide valid number of shares", 400)

        shares = int(shares)
        price = quote["price"]
        total_cost = price * shares  # Calculate total cost

        # Ensure user has enough funds
        user_id = session["user_id"]
        cash = db.execute("SELECT cash FROM users WHERE id = ?", user_id)[0]["cash"]
        if total_cost > cash:
            return apology("not enough funds", 400)

        # Update user's cash balance
        db.execute("UPDATE users SET cash = cash - ? WHERE id = ?", total_cost, user_id)

        # Record the transaction
        db.execute("""
            INSERT INTO transactions (user_id, symbol, shares, price)
            VALUES (?, ?, ?, ?)
        """, user_id, symbol, shares, price)

        flash("Bought!")
        return redirect("/")

    return render_template("buy.html", stock=None)


@app.route("/history")
@login_required
def history():
    """Show history of transactions"""
    user_id = session["user_id"]

    # Get all transactions of the user
    transactions = db.execute("""
        SELECT symbol, shares, price, time
        FROM transactions
        WHERE user_id = ?
        ORDER BY time DESC
    """, user_id)

    return render_template("history.html", transactions=transactions)


@app.route("/login", methods=["GET", "POST"])
def login():
    """Log user in"""

    # Forget any user_id
    session.clear()

    # User reached route via POST (as by submitting a form via POST)
    if request.method == "POST":
        # Ensure username was submitted
        if not request.form.get("username"):
            return apology("must provide username", 403)

        # Ensure password was submitted
        elif not request.form.get("password"):
            return apology("must provide password", 403)

        # Query database for username
        rows = db.execute(
            "SELECT * FROM users WHERE username = ?", request.form.get("username")
        )

        # Ensure username exists and password is correct
        if len(rows) != 1 or not check_password_hash(
            rows[0]["hash"], request.form.get("password")
        ):
            return apology("invalid username and/or password", 403)

        # Remember which user has logged in
        session["user_id"] = rows[0]["id"]

        # Redirect user to home page
        return redirect("/")

    # User reached route via GET (as by clicking a link or via redirect)
    else:
        return render_template("login.html")


@app.route("/logout")
def logout():
    """Log user out"""

    # Forget any user_id
    session.clear()

    # Redirect user to login form
    return redirect("/")


@app.route("/quote", methods=["GET", "POST"])
@login_required
def quote():
    """Get stock quote."""
    if request.method == "POST":
        # Get the stock symbol entered by the user
        symbol = request.form.get("symbol")

        if not symbol:
            return apology("must provide symbol", 400)

        quote = lookup(symbol)

        if not quote:
            return apology("invalid symbol", 400)

        return render_template("quote.html", quote=quote)

    return render_template("quote.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    """Register user"""
    if request.method == "POST":
        # Ensure username and password are provided
        username = request.form.get("username")
        password = request.form.get("password")
        confirmation = request.form.get("confirmation")

        if not username:
            return apology("must provide username", 400)

        if not password:
            return apology("must provide password", 400)

        if password != confirmation:
            return apology("passwords must match", 400)

        # Check if username already exists
        existing_user = db.execute("SELECT * FROM users WHERE username = ?", username)
        if len(existing_user) > 0:
            return apology("username already taken", 400)

        # Insert new user into database
        db.execute(
            "INSERT INTO users (username, hash) VALUES (?, ?)",
            username,
            generate_password_hash(password)
        )

        flash("Registered!")
        return redirect("/login")

    return render_template("register.html")


@app.route("/sell", methods=["GET", "POST"])
@login_required
def sell():
    """Sell shares of stock"""
    user_id = session["user_id"]

    # Get all stocks the user owns
    stocks = db.execute("""
        SELECT symbol, SUM(shares) AS shares
        FROM transactions
        WHERE user_id = ?
        GROUP BY symbol
    """, user_id)

    if request.method == "POST":
        symbol = request.form.get("symbol")
        shares = int(request.form.get("shares"))

        # Ensure the user owns enough shares to sell
        owned_shares = next((stock for stock in stocks if stock['symbol'] == symbol), None)
        if not owned_shares or shares > owned_shares["shares"]:
            return apology("you do not own enough shares", 400)

        # Get the current price of the stock
        quote = lookup(symbol)
        price = quote["price"]
        total_revenue = price * shares

        # Update the user's cash balance
        db.execute("UPDATE users SET cash = cash + ? WHERE id = ?", total_revenue, user_id)

        # Record the transaction (selling shares as a negative number)
        db.execute("""
            INSERT INTO transactions (user_id, symbol, shares, price)
            VALUES (?, ?, ?, ?)
        """, user_id, symbol, -shares, price)

        flash("Sold!")
        return redirect("/")

    return render_template("sell.html", stocks=stocks)
