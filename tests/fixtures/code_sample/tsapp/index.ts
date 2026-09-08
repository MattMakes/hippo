import { Order, OrderModel } from "./models/order";

export function main() {
  const o = new Order();
  o.total();
  console.log(o);
  return OrderModel.find({});
}
