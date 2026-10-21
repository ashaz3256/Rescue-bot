# Test photos

Put 20 or so photos here, taken at **car height** (about 10 cm off the floor), and mix them up:

- empty rooms and hallways
- someone lying on the floor at 1, 2, 3 and 5 m
- someone partly hidden (behind a chair, legs only, under a blanket)
- obstacles close up, doorways, dim lighting

Then copy `answers.example.csv` to `answers.csv` and fill in one row per photo:
`person` = yes/no, `distance_m` = rough distance (blank if no person).

Run `python brain/vision_test.py` to score each model.
