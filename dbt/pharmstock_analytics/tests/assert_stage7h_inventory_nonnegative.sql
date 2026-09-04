select *
from {{ ref('stg7h_inventory_position') }}
where on_hand_units < 0
   or reserved_units < 0
   or available_units < 0
   or reserved_units > on_hand_units
