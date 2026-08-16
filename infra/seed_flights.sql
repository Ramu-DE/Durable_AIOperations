-- Seed data: flights and pre-allocated seat rows
-- Each seat_holds row represents one physical seat; status='available' = open for booking.

INSERT INTO flights (flight_id, origin, destination, departs_at) VALUES
  ('FL-100', 'JFK', 'LAX', now() + interval '2 days'),
  ('FL-101', 'JFK', 'LAX', now() + interval '3 days'),
  ('FL-200', 'BOS', 'SFO', now() + interval '2 days')
ON CONFLICT DO NOTHING;

-- FL-100: 1 economy seat (for OCC race demo), 3 business
INSERT INTO seat_holds (hold_id, flight_id, seat_number, seat_class, price_usd) VALUES
  ('FL100-1A', 'FL-100', '1A', 'economy',  199.00),
  ('FL100-2A', 'FL-100', '2A', 'business', 499.00),
  ('FL100-2B', 'FL-100', '2B', 'business', 499.00),
  ('FL100-2C', 'FL-100', '2C', 'business', 499.00)
ON CONFLICT DO NOTHING;

-- FL-101: normal inventory
INSERT INTO seat_holds (hold_id, flight_id, seat_number, seat_class, price_usd) VALUES
  ('FL101-1A', 'FL-101', '1A', 'economy',  209.00),
  ('FL101-1B', 'FL-101', '1B', 'economy',  209.00),
  ('FL101-2A', 'FL-101', '2A', 'business', 519.00)
ON CONFLICT DO NOTHING;

-- FL-200: normal inventory
INSERT INTO seat_holds (hold_id, flight_id, seat_number, seat_class, price_usd) VALUES
  ('FL200-1A', 'FL-200', '1A', 'economy',  299.00),
  ('FL200-1B', 'FL-200', '1B', 'economy',  299.00),
  ('FL200-2A', 'FL-200', '2A', 'business', 699.00)
ON CONFLICT DO NOTHING;
