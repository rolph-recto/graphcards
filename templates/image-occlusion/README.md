# Image occlusion study

This template defines one image-occlusion generator. The image path is relative to this deck
directory. It includes a supported raster example image at `assets/solar-system.jpg`, credited to
NASA/Lunar and Planetary Institute via [NASA Science](https://science.nasa.gov/resource/solar-system-sizes/).

Each occlusion target is an entity. The generator creates one FSRS card for each target and stores
the rectangle in normalized coordinates from 0 to 1. The included image shows the planets in
correct order and relative sizes. The default front hides the target region and shows a `?`
marker. The `answer` render slot selects the entity's `answer` value. `image_path` remains a
separate deck-relative generation setting.
