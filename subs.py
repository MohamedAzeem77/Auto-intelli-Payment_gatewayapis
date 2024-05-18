from flask import Flask, redirect, url_for, request, jsonify , render_template
from flask_mail import Mail, Message
from flask_sqlalchemy import SQLAlchemy
import stripe, uuid
from datetime import datetime, timedelta

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'postgresql://postgres:azeem@localhost:5432/subscribetable'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

stripe.api_key = "sk_test_51P9hmVSEEqXDiDF9SqS2mLik6d5emBflRIcwaDmzXm0maFXdey0hwNda8YPJl5NRlQzGgf8xjYhuDGXvG6Q9wTmq00qGB3Bgkp"

# Email configuration
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 465
app.config['MAIL_USERNAME'] = 'mohamedazeems069@gmail.com'
app.config['MAIL_PASSWORD'] = 'mnlxquubpwepqfxo'
app.config['MAIL_USE_TLS'] = False
app.config['MAIL_USE_SSL'] = True
mail = Mail(app)


class Transaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    product_name = db.Column(db.String(100))
    currency = db.Column(db.String(10))
    amount = db.Column(db.Integer)
    success = db.Column(db.Boolean)
    customer_email = db.Column(db.String(100))
    receipt_number = db.Column(db.String(100))
    subscription_type = db.Column(db.String(50))  # New field for subscription type (e.g., 'monthly', 'yearly')
    subscription_start_date = db.Column(db.DateTime, default=datetime.utcnow)  # New field for start date
    subscription_end_date = db.Column(db.DateTime)  # New field for end date
    subscription_status = db.Column(db.String(20), default='subscribed')

    def __repr__(self):
        return f'<Transaction {self.id}: {self.product_name}, {self.receipt_number}, {self.subscription_type}>'

    def calculate_subscription_end_date(self):
        if self.subscription_type == 'yearly':
            self.subscription_end_date = self.subscription_start_date + timedelta(days=365)
        elif self.subscription_type == 'monthly':
            self.subscription_end_date = self.subscription_start_date + timedelta(days=30)
        else:
            raise ValueError("Invalid subscription type")

        return self.subscription_end_date


with app.app_context():
    db.create_all()


def send_email(transaction):
    msg = Message("Payment Successful",
                  sender="mohamedazeems069@gmail.com",
                  recipients=[transaction.customer_email])
    msg.body = f"Your payment for {transaction.product_name} has been processed successfully. Receipt No: {transaction.receipt_number}"
    mail.send(msg)


@app.route("/")
def index():
    return  render_template(checkout.html)



# Route to render the HTML form
@app.route("/checkout", methods=["GET"])
def show_checkout_form():
    return render_template("checkout.html")


@app.route("/checkout", methods=["POST"])
def checkout():
    # Extract data from form fields
    customer_email = request.form.get("customer_email")
    subscription_type = request.form.get("subscription_type")  # 'monthly' or 'yearly'

    if not customer_email:
        return jsonify({"error": "Email not provided"}), 400
    if not subscription_type or subscription_type not in ['monthly', 'yearly']:
        return jsonify({"error": "Invalid or no subscription type provided"}), 400

    # Define line item based on the subscription type
    if subscription_type == 'monthly':
        price_id = 'price_1PGflnSEEqXDiDF9bdGHFzM6'
        product_name = 'Monthly Subscription'
    else:
        price_id = 'price_1PGfnbSEEqXDiDF9XsSI9jgi'
        product_name = 'Yearly Subscription'

    line_item = {
        'price': price_id,
        'quantity': 1
    }

    receipt_number = str(uuid.uuid4())


    try:
        session = stripe.checkout.Session.create(
            customer_email=customer_email,
            billing_address_collection='auto',
            payment_method_types=['card'],
            line_items=[line_item],
            mode='subscription',
            success_url=url_for("payment_success", receipt_number=receipt_number, _external=True),
            cancel_url=url_for("payment_failure", _external=True)
        )

        amount = session.amount_total / 100
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    subscription_start_date = datetime.utcnow()

    new_transaction = Transaction(
        product_name=f"{'Monthly' if subscription_type == 'monthly' else 'Yearly'} Subscription",
        currency='inr',
        amount=amount,  # Since price is now fetched from Stripe, set amount to None
        success=False,
        customer_email=customer_email,
        receipt_number=receipt_number,
        subscription_type=subscription_type,
        subscription_start_date=subscription_start_date,

    )
    new_transaction.calculate_subscription_end_date()

    new_transaction.stripe_subscription_id = session.subscription

# Assign Stripe subscription ID to the transaction

    db.session.add(new_transaction)
    db.session.commit()

    return redirect(session.url)


# Cancel Subscription API
@app.route("/subscription/cancel", methods=["POST"])
def cancel_subscription():
    if not request.is_json:
        return jsonify({"error": "Invalid content type. Please use 'Content-Type: application/json'"}), 400

    data = request.get_json()
    customer_email = data.get("customer_email")

    if not customer_email:
        return jsonify({"error": "Email not provided"}), 400

    latest_transaction = Transaction.query.filter_by(customer_email=customer_email).order_by(
        Transaction.subscription_start_date.desc()).first()

    if latest_transaction:
        if latest_transaction.success:
            try:
                latest_transaction.subscription_status = 'cancelled'
                db.session.delete(latest_transaction)
                db.session.commit()

                # Send email notification
                send_cancelled_subscription_email(latest_transaction)

                return jsonify({"message": "Subscription cancelled successfully"}), 200
            except Exception as e:
                db.session.rollback()
                return jsonify({"error": str(e)}), 500
        else:
            return jsonify({"error": "Subscription cannot be cancelled as payment was not successful"}), 400
    else:
        return jsonify({"error": "No subscription found for the provided email"}), 404


def send_cancelled_subscription_email(transaction):
    msg = Message("Subscription Cancelled",
                  sender="mohamedazeems069@gmail.com",
                  recipients=[transaction.customer_email])
    msg.body = f"Your subscription for {transaction.product_name} has been cancelled. We hope to see you again soon!"
    mail.send(msg)


@app.route("/payment/success")
def payment_success():
    receipt_number = request.args.get('receipt_number')
    transaction = Transaction.query.filter_by(receipt_number=receipt_number).first()
    if transaction:
        transaction.success = True
        db.session.commit()
        send_email(transaction)

        # Render the payment success template and pass receipt_number to it
        return render_template("payment_success.html", receipt_number=receipt_number)
    return "Error: Transaction not found."


@app.route("/payment/failure")
def payment_failure():
    return "Payment was cancelled or failed.", 200


# Get UI Payment datas
@app.route("/payments", methods=["GET"])
def get_payments():
    payment_intent_id = request.args.get('payment_intent_id')
    # customer_email = request.args.get('customer_email')
    fetch_all = request.args.get('all') == 'true'

    if payment_intent_id:
        # Fetch a specific payment intent
        try:
            payment_intent = stripe.PaymentIntent.retrieve(payment_intent_id)
            return jsonify(payment_intent), 200
        except stripe.error.StripeError as e:
            return jsonify(error=str(e)), 400

    elif fetch_all:
        # Fetch all payment intents with a reasonable limit
        try:
            all_payments = stripe.PaymentIntent.list(limit=100)  # Limit can be adjusted based on your needs
            return jsonify([p for p in all_payments.auto_paging_iter()]), 200
        except stripe.error.StripeError as e:
            return jsonify(error=str(e)), 400

    return jsonify({"error": "Please provide a Payment Intent ID, a Customer Email, or set 'all' to true"}), 400


# GET_BY_Receipt_number  from db
@app.route("/transactions", methods=["GET"])
def get_transactions():
    customer_email = request.args.get("customer_email")
    receipt_number = request.args.get("receipt_number")

    query = Transaction.query

    if customer_email:
        query = query.filter(Transaction.customer_email == customer_email)
    if receipt_number:
        query = query.filter(Transaction.receipt_number == receipt_number)

    transactions = query.all()
    transactions_data = [{
        "product_name": transaction.product_name,
        "currency": transaction.currency,
        "amount": transaction.amount,
        "success": transaction.success,
        "customer_email": transaction.customer_email,
        "receipt_number": transaction.receipt_number
    } for transaction in transactions]

    return jsonify(transactions_data)


# GET ALL  from  db
@app.route("/transactions", methods=["GET"])
def get_alltransactions():
    transactions = Transaction.query.all()

    transactions_data = [{
        "product_name": transaction.product_name,
        "currency": transaction.currency,
        "amount": transaction.amount,
        "success": transaction.success,
        "customer_email": transaction.customer_email,
        "receipt_number": transaction.receipt_number
    } for transaction in transactions]

    return jsonify(transactions_data)


if __name__ == "__main__":
    app.run(port=4242, debug=True)
