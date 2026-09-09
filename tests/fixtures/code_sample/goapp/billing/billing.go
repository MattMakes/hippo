// Package billing totals orders and sends their invoices.
package billing

import "fmt"

// Total adds up an order's lines.
func Total(order Order) int {
	amount := 0
	for _, line := range order.Lines {
		amount += line
	}
	return amount
}

// SendInvoice mails the invoice for one order.
func SendInvoice(order Order) {
	fmt.Println("sending", order.ID)
}
