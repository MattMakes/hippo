package main

import "example.com/goapp/orders"

func main() {
	service := orders.Service{}
	service.Place(orders.Order{})
}
