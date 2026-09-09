// Package store holds what every service embeds.
package store

// Base is a tiny base type.
type Base struct{}

// Log returns the message it was handed.
func (b *Base) Log(message string) string {
	return message
}

// OrderError is what an order returns when it will not save.
type OrderError struct{}
