select *
from {{ ref('fct_daily_inventory_movement') }}
where opening_observed_on_hand < 0
   or closing_observed_on_hand < 0
   or movement_events < 1
