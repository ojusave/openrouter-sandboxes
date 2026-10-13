import unittest
from totals import invoice_total

class ShippingTests(unittest.TestCase):
    def test_shipping(self):
        self.assertEqual(invoice_total([{"unit_price_cents": 125, "quantity": 3}], shipping_cents=50), 425)

if __name__ == "__main__":
    unittest.main()
