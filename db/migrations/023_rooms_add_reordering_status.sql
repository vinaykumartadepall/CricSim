ALTER TABLE simulation.rooms
    DROP CONSTRAINT IF EXISTS rooms_status_check;

ALTER TABLE simulation.rooms
    ADD CONSTRAINT rooms_status_check
        CHECK (status IN ('waiting','drafting','reordering','simulating','completed'));
