import * as migration_20251008_195827_user_access from './20251008_195827_user_access'
import * as migration_20251008_223642_dummy_1 from './20251008_223642_dummy_1'
import * as migration_20251010_202527_dashboard_item_add_height from './20251010_202527_dashboard_item_add_height'
import * as migration_20251029_225149_add_suggested_items_collection from './20251029_225149_add_suggested_items_collection'
import * as migration_20251029_231907_add_new_session_welcome_collection from './20251029_231907_add_new_session_welcome_collection'

export const migrations = [
  {
    up: migration_20251008_195827_user_access.up,
    down: migration_20251008_195827_user_access.down,
    name: '20251008_195827_user_access',
  },
  {
    up: migration_20251008_223642_dummy_1.up,
    down: migration_20251008_223642_dummy_1.down,
    name: '20251008_223642_dummy_1',
  },
  {
    up: migration_20251010_202527_dashboard_item_add_height.up,
    down: migration_20251010_202527_dashboard_item_add_height.down,
    name: '20251010_202527_dashboard_item_add_height',
  },
  {
    up: migration_20251029_225149_add_suggested_items_collection.up,
    down: migration_20251029_225149_add_suggested_items_collection.down,
    name: '20251029_225149_add_suggested_items_collection',
  },
  {
    up: migration_20251029_231907_add_new_session_welcome_collection.up,
    down: migration_20251029_231907_add_new_session_welcome_collection.down,
    name: '20251029_231907_add_new_session_welcome_collection',
  },
]
