import { Base } from "./base";
import mongoose from "mongoose";

/**
 * An order. This class is long enough to have a real doc comment, over eighty characters.
 */
export class Order extends Base {
  total(): number {
    return compute(this);
  }
}

export const compute = (o: Order): number => {
  return 1;
};

export const OrderModel = mongoose.model("Order", new mongoose.Schema({}));
