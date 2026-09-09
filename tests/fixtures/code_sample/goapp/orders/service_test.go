package orders

import "testing"

func TestPlace(t *testing.T) {
	(&Service{}).Place(Order{})
}
