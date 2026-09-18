// Package orders places, stores and archives customer orders.
package orders

import (
	"database/sql"

	"example.com/goapp/billing"
	"example.com/goapp/store"
)

// Service keeps orders. Every order is totalled by the billing package, written to Postgres as
// one row and copied into the archive collection the reporting team reads.
//
// Second paragraph, not part of the first.
type Service struct {
	store.Base

	db *sql.DB
}

// Place totals an order with billing, sends its invoice and logs the route the order took
// before handing back the amount the customer owes.
func (s *Service) Place(order Order) int {
	amount := billing.Total(order)
	billing.SendInvoice(order)
	s.Log("x")
	return amount
}

func (s *Service) Log(message string) string {
	return message
}

func (s *Service) ListOpen() {
	s.db.Query("SELECT id, total FROM orders WHERE status = 'open'")
}

func (s *Service) Save(order Order) error {
	s.db.Exec("INSERT INTO orders (id, total) VALUES ($1, $2)")
	return &store.OrderError{}
}

func (s *Service) Archive(order Order) {
	coll := client.Database("app").Collection("archive_orders")
	coll.InsertOne(ctx, order)
}

func (s *Service) Graph() {
	session.Run("MATCH (o:Order)-[:PLACED_BY]->(c:Customer) RETURN c", nil)
}
