import datetime
import csv

with open('datafiles/public_chat.csv', 'w') as csvfile:
    writer = csv.writer(csvfile, delimiter=',')
    writer.writerow(
        [
            (datetime.datetime.now() + datetime.timedelta(seconds=4)).strftime("%Y.%m.%d %H:%M:%S"),
            'Guido',
            'massage_2'
        ]
    )
    writer.writerow(
        [
            str((datetime.datetime.now() + datetime.timedelta(seconds=2)).strftime("%Y.%m.%d %H:%M:%S")),
            'Dave',
            'massage_1'
        ]
    )
    writer.writerow(
        [
            datetime.datetime.now().strftime("%Y.%m.%d %H:%M:%S"),
            'Susan',
            'massage'
        ]
    )

with open('datafiles/public_chat.csv', 'r') as csvfile:
    reader = csv.reader(csvfile, delimiter=',')
    for row in reader:
        print(row)
