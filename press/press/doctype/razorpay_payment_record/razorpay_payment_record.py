# Copyright (c) 2022, Frappe and contributors
# For license information, please see license.txt
from __future__ import annotations

from datetime import datetime, timedelta

import frappe
from frappe.model.document import Document

from press.press.doctype.team.team import _enqueue_finalize_unpaid_invoices_for_team
from press.utils import log_error
from press.utils.billing import get_razorpay_client


class RazorpayPaymentRecord(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		failure_reason: DF.SmallText | None
		order_id: DF.Data | None
		payment_id: DF.Data | None
		signature: DF.Data | None
		status: DF.Literal["Captured", "Failed", "Pending"]
		team: DF.Link | None
		type: DF.Literal["Prepaid Credits", "Partnership Fee"]
	# end: auto-generated types

	def on_update(self):
		if self.has_value_changed("status") and self.status == "Captured":
			if self.type == "Prepaid Credits":
				self.process_prepaid_credits()
			elif self.type == "Partnership Fee":
				self.process_partnership_fee()

	def process_prepaid_credits(self):
		team = frappe.get_doc("Team", self.team)

		client = get_razorpay_client()
		payment = client.payment.fetch(self.payment_id)
		amount_with_tax = payment["amount"] / 100
		gst = float(payment["notes"].get("gst", 0))
		amount = amount_with_tax - gst
		balance_transaction = team.allocate_credit_amount(
			amount,
			source="Prepaid Credits",
			remark=f"Razorpay: {self.payment_id}",
		)
		team.reload()

		# Add a field to track razorpay event
		invoice = frappe.get_doc(
			doctype="Invoice",
			team=team.name,
			type="Prepaid Credits",
			status="Paid",
			due_date=datetime.fromtimestamp(payment["created_at"]),
			total=amount,
			amount_due=amount,
			gst=gst or 0,
			amount_due_with_tax=amount_with_tax,
			amount_paid=amount_with_tax,
			razorpay_order_id=self.order_id,
			razorpay_payment_record=self.name,
			razorpay_payment_method=payment["method"],
		)
		invoice.append(
			"items",
			{
				"description": "Prepaid Credits",
				"document_type": "Balance Transaction",
				"document_name": balance_transaction.name,
				"quantity": 1,
				"rate": amount,
			},
		)
		invoice.insert()
		invoice.reload()

		invoice.update_razorpay_transaction_details(payment)
		invoice.submit()

		_enqueue_finalize_unpaid_invoices_for_team(team.name)

	def process_partnership_fee(self):
		team = frappe.get_doc("Team", self.team)

		client = get_razorpay_client()
		payment = client.payment.fetch(self.payment_id)
		amount_with_tax = payment["amount"] / 100
		gst = float(payment["notes"].get("gst", 0))
		amount = amount_with_tax - gst
		balance_transaction = team.allocate_credit_amount(
			amount,
			source="Prepaid Credits",
			remark=f"Razorpay: {self.payment_id}",
			type="Partnership Fee",
		)
		team.reload()

		# Add a field to track razorpay event
		invoice = frappe.get_doc(
			doctype="Invoice",
			team=team.name,
			type="Partnership Fees",
			status="Paid",
			due_date=datetime.fromtimestamp(payment["created_at"]),
			total=amount,
			amount_due=amount,
			gst=gst or 0,
			amount_due_with_tax=amount_with_tax,
			amount_paid=amount_with_tax,
			razorpay_order_id=self.order_id,
			razorpay_payment_record=self.name,
			razorpay_payment_method=payment["method"],
		)
		invoice.append(
			"items",
			{
				"description": "Partnership Fee",
				"document_type": "Balance Transaction",
				"document_name": balance_transaction.name,
				"quantity": 1,
				"rate": amount,
			},
		)
		invoice.insert()
		invoice.reload()

		invoice.update_razorpay_transaction_details(payment)
		invoice.submit()

	@frappe.whitelist()
	def sync(self):
		try:
			client = get_razorpay_client()
			response = client.order.payments(self.order_id)

			for item in response.get("items"):
				if item["status"] == "captured":
					frappe.get_doc(
						{
							"doctype": "Razorpay Webhook Log",
							"payload": frappe.as_json(item),
							"event": "order.paid",
							"payment_id": item["id"],
							"name": item["order_id"],
						}
					).insert(ignore_if_duplicate=True)
		except Exception:
			log_error(title="Failed to sync Razorpay Payment Record", order_id=self.order_id)


def fetch_pending_payment_orders(hours=12):
	past_12hrs_ago = datetime.now() - timedelta(hours=hours)
	pending_orders = frappe.get_all(
		"Razorpay Payment Record",
		dict(status="Pending", creation=(">=", past_12hrs_ago)),
		pluck="order_id",
	)

	client = get_razorpay_client()
	if not pending_orders:
		return

	for order_id in pending_orders:
		try:
			response = client.order.payments(order_id)
			for item in response.get("items"):
				if item["status"] == "captured":
					frappe.get_doc(
						{
							"doctype": "Razorpay Webhook Log",
							"payload": frappe.as_json(item),
							"event": "order.paid",
							"payment_id": item["id"],
							"name": item["order_id"],
						}
					).insert(ignore_if_duplicate=True)
		except Exception:
			log_error(title="Failed to capture pending order", order_id=order_id)

	"""
	Sample Response
	ref: https://razorpay.com/docs/api/orders/#fetch-payments-for-an-order

	{
		"entity": "collection",
		"count": 1,
		"items": [
			{
				"id": "pay_JhOBNkFZFi0EOX",
				"entity": "payment",
				"amount": 100,
				"currency": "INR",
				"status": "captured",
				"order_id": "order_DaaS6LOUAASb7Y",
				"invoice_id": null,
				"international": false,
				"method": "card",
				"amount_refunded": 0,
				"refund_status": null,
				"captured": true,
				"description": "",
				"card_id": "card_Be7AhhLtm1gxzc",
				"bank": null,
				"wallet": null,
				"vpa": null,
				"email": "gaurav.kumar@example.com",
				"contact": "+919900000000",
				"customer_id": "cust_Be6N4O63pXzmqK",
				"token_id": "token_BhNxzjrZvkqLWr",
				"notes": [],
				"fee": 0,
				"tax": 0,
				"error_code": null,
				"error_description": null,
				"error_source": null,
				"error_step": null,
				"error_reason": null,
				"acquirer_data": {
					"auth_code": null
				},
				"created_at": 1655212834
			}
		]
	}
	"""
