import uuid
import json
import requests
import datetime

import logging
import telegram

from modules import RaspOneBaseModule
from src import DEFAULT_NAME

module_logger = logging.getLogger(DEFAULT_NAME + ".module.italo")


class ModuleItalo(RaspOneBaseModule):
    NAME = "italo"
    DESCRIPTION = "Search Italo trains"

    USAGE = {
        "seats": "Search and get seats for a train"
    }

    def __init__(self, core):
        super().__init__(core)

        self.tm = TrainManager()

    async def command(self, update, context):
        message = ""
        markdown = None
        if context.args[0].lower() == "seats":
            context.args.pop(0)
            if len(context.args) != 1 or not context.args[0].isnumeric():
                message = "Error: expecting one Train Number!"

            else:
                train_schedule, error = self._get_train(context.args[0])
                if error:
                    message = str(error)

                else:
                    await update.effective_message.reply_text(
                        "🚂 Train: {TrainNumber}\n"
                        "From: {DepartureStationDescription} ({DepartureDate})"
                        " - To: {ArrivalStationDescription} ({ArrivalDate})\n"
                        "Stops:\n".format_map(train_schedule) +
                        "\n".join(
                            "  • {LocationDescription} ({ActualArrivalTime} - {ActualDepartureTime})".format_map(
                                stop)
                            for stop in train_schedule["StazioniNonFerme"]) +
                        "\n\n _Searching for seats.. (this may take a while)_",
                        parse_mode=telegram.constants.ParseMode.MARKDOWN
                    )

                    page_url, error = self._get_seats_and_upload(context.args[0])
                    if error:
                        message = str(error)

                    else:
                        message = f"🚂 Done: [Italo {context.args[0]}]({page_url})"
                        markdown = telegram.constants.ParseMode.MARKDOWN

        await update.effective_message.reply_text(message, parse_mode=markdown)

    def _get_train(self, train_number):
        try:

            train_schedule = self.tm.search_train(train_number)
            return train_schedule, None

        except Exception as error:
            return False, error

    def _get_seats_and_upload(self, train_number):
        try:
            page_html = self.tm.search_seats()
            file_key = uuid.uuid4().urn[9:] + "/italo_%s.html" % train_number
            object_url, error = self.core.modules["instances"]["s3"].add_object(file_key, page_html, "text/html")
            if error:
                raise error

            return object_url, None

        except Exception as error:
            return False, error


# BELOW ITALO CODE - REMEMBER TO COMMENT print()


class ItaloError(Exception):
    """Italo Error"""


class UserError(Exception):
    """User Error"""


train_mapping = {
    "AGV": {
        "1": 869, "2": 870, "3": 871, "4": 872, "5": 873, "6": 874, "7": 875, "8": 876, "9": 877, "10": 878, "11": 879
    },
    "EVO": {
        "1": 880, "2": 881, "3": 882, "4": 883, "5": 884, "6": 885, "7": 886
    },
    "EVI": {
        "1A": 880, "2A": 881, "3A": 882, "4A": 883, "5A": 884, "6A": 885, "7A": 886,
        "1B": 880, "2B": 881, "3B": 882, "4B": 883, "5B": 884, "6B": 885, "7B": 886
    }
}


class TrainManager:
    def __init__(self):
        self.session = requests.Session()

        # self.session.verify = False
        # self.session.proxies = {"https": "https://127.0.0.1:8080"}

        self.signature = None
        self.train_schedule = None
        self.train_type = None

    def retrieve_realtime(self, train_number: int):
        response = self.session.get("https://italoinviaggio.italotreno.it/api/RicercaTrenoService"
                                    "?TrainNumber=%s" % train_number)

        try:
            response_json = response.json()
            if response_json["IsEmpty"]:
                raise UserError("Invalid train number")

            self.train_schedule = response_json["TrainSchedule"]

        except (requests.exceptions.RequestException, Exception):
            raise UserError("Invalid train number")

    def get_session(self):
        login_response = self.session.post("https://big.ntvspa.it/BIG/v7/Rest/SessionManager.svc/Login",
                                           json={"Login": {
                                               "Username": "WWW_Anonymous", "Password": "Accenture$1", "Domain": "WWW",
                                               "VersionNumber": "3.0.6"
                                           }, "SourceSystem": 2})

        try:
            login_json = login_response.json()
            if "Signature" not in login_json:
                raise ItaloError("Invalid login")

            self.signature = login_json["Signature"]

        except (requests.exceptions.RequestException, Exception):
            raise ItaloError("Invalid login")

    def clear_session(self):
        self.session.post("https://big.ntvspa.it/BIG/v7/Rest/SessionManager.svc/ClearSession",
                          json={"LoyaltyTransactionId": None, "Signature": self.signature})

    def get_available_trains(self, departure_station, arrival_station, interval_start_time, interval_end_time):
        available_response = self.session.post("https://big.ntvspa.it/BIG/v7/Rest/BookingManager.svc"
                                               "/GetAvailableTrains", json={
            "GetAvailableTrains": {"RoundTrip": False,
                                   "DepartureStation": departure_station.replace("BO2", "BC_"),
                                   "ArrivalStation": arrival_station.replace("BO2", "BC_"),
                                   "IntervalStartDateTime": interval_start_time,
                                   "IntervalEndDateTime": interval_end_time,
                                   "RoundTripIntervalStartDateTime": interval_start_time,
                                   "RoundTripIntervalEndDateTime": interval_end_time,
                                   "AdultNumber": 1,
                                   "YoungNumber": 0, "ChildNumber": 0, "InfantNumber": 0, "SeniorNumber": 0,
                                   "CurrencyCode": "EUR", "ProductClass": None, "RoundtripProductClass": None,
                                   "ProductName": None, "FareType": None, "FareClassOfService": None,
                                   "ShowNestedSSR": True, "InfoBoat": None, "JourneySpecialOperation": None,
                                   "AncillaryService": None, "Promocode": None, "AgentPromotion": None, "IsGuest": True,
                                   "OverrideIntervalTimeRestriction": True, "AvailabilityFilter": 1,
                                   "FareClassControl": 0, "IDPartner": None},
            "Signature": self.signature,
            "SourceSystem": 2})

        try:
            available_json = available_response.json()
            if "Code" in available_json and available_json["Code"] == 1033:
                raise ItaloError("Invalid session")

            elif not available_json["JourneyDateMarkets"][0]["Journeys"]:
                raise ItaloError("Invalid train")

            for journey in available_json["JourneyDateMarkets"][0]["Journeys"]:
                if not self.train_schedule["TrainNumber"] in journey["JourneySellKey"]:
                    continue

                fare_sell_keys = []
                if journey["Segments"][0]["Fares"] and len(journey["Segments"][0]["Fares"]):
                    fare_sell_keys = [fare["FareSellKey"] for fare in journey["Segments"][0]["Fares"]]

                return journey["JourneySellKey"], fare_sell_keys

            raise ItaloError("Invalid train detail")

        except (requests.exceptions.RequestException, Exception):
            raise ItaloError("Invalid train detail")

    def hold_booking(self, journey_sell_key, fare_sell_key):
        booking_response = self.session.post("https://big.ntvspa.it/BIG/v7/Rest/BookingManager.svc/HoldBooking", json={
            "Signature": self.signature,
            "SourceSystem": 2, "Journeys": [{"CurrencyCode": "EUR", "FareSellKey": fare_sell_key,
                                             "JourneySellKey": journey_sell_key,
                                             "Amount": None, "SegmentSeatRequest": None,
                                             "PassengerSeatPreference": None}],
            "Passengers": [{"EmailAddress": "dummy.dummy@gmail.com", "PaxType": "ADT", "Phone": "123456789"}],
            "BookingContact": {"DistributionOption": 1, "Culture": 1}, "WaiveFee": False, "RequestFareLock": False,
            "JourneySpecialOperation": None, "AncillaryService": None, "RequestAncillaryService": True,
            "RequestPetAncillaryService": False, "AssetNumber": None
        })

        try:
            booking_json = booking_response.json()
            if "Code" in booking_json:
                if booking_json["Code"] == 1513:
                    return None

                elif booking_json["Code"] == 1004:
                    return None

                # if booking_json["Code"] == 1033:
                raise ItaloError("Invalid session")

            elif "Booking" not in booking_json:
                raise ItaloError("Invalid booking response")

            return True

        except (requests.exceptions.RequestException, Exception):
            raise ItaloError("Invalid booking")

    def get_seat_availability(self, segment_sell_key):
        seat_response = self.session.post("https://big.ntvspa.it/BIG/v7/Rest/BookingManager.svc/GetSeatAvailability",
                                          json={"Signature": self.signature,
                                                "Segment": {"SegmentSellKey": segment_sell_key}, "SourceSystem": 2})

        try:
            seat_json = seat_response.json()
            if "Code" in seat_json:
                if seat_json["Code"] == 1513:
                    return None

                # if seat_json["Code"] == 1033:
                # raise ItaloError("Invalid session")

                return None

            elif "Equipment" not in seat_json:
                raise ItaloError("Invalid seat availability response")

            return seat_json

        except (requests.exceptions.RequestException, Exception):
            raise ItaloError("Invalid booking")

    def get_grm_content(self, grm_id):
        grm_response = self.session.post("https://big.ntvspa.it/BIG/v7/Rest/BookingManager.svc/GetGRMContent",
                                         json={"ContentID": grm_id, "MD5checksum": "", "SourceSystem": 2})

        try:
            grm_json = grm_response.json()
            if "Data" not in grm_json:
                raise ItaloError("Invalid GRM response")

            return bytearray(grm_json["Data"]).decode().replace('data-name="not_available"',
                                                                'data-name="not_available" visibility="hidden"')

        except (requests.exceptions.RequestException, Exception):
            raise ItaloError("Invalid grm")

    def create_grm_map(self):
        if not self.train_type:
            return "<h3>The train is full</h3>"

        grm_map_html = ""
        for compartment_number in sorted([int(x) for x in train_mapping[self.train_type].keys()]):
            grm_map_html += "<div class='compartment'>"

            grm_map_html += "<div>" + self.get_grm_content(
                train_mapping[self.train_type][str(compartment_number)]) + "</div>"

            grm_map_html += "<div><h1>Compartment {0}</h1>" \
                            "<div id='compartment-detail-{0}' class='compartment-detail'></div>" \
                            "</div>".format(compartment_number)

            grm_map_html += "</div>"

        return grm_map_html

    def create_html(self, segments):
        page_html = """<html>
        <head>
        <style>
                body {
            font-family: sans-serif;
            text-align: center;
        }
        .train-segments {
            display: grid;
            grid-template-columns: 80% 20%;
            grid-gap: 2px;
        }
        .compartment {
            display: grid;
            grid-template-columns: 40% 55%;
            grid-gap: 20px;
        }
        red {
            color: #7c0f06;
        }
        green {
            color: #0bc4a5;
            font-weight: bold;
        }
        </style>
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        </head>
        <body>
            <h1>Train """ + str(self.train_schedule["TrainNumber"]) + "</h1>\n"
        page_html += "<div class=\"train-segments\">\n"
        for x in range(len(segments)):
            page_html += "<div>%s</div>" % segments[x]["code"]
            page_html += "<div><button onclick=\"showSeat(%d)\">SHOW</button></div>\n" % x

        page_html += "<div></div><div><button onclick=\"showSeat()\">RESET</button></div>\n"
        page_html += "</div><br/>"
        page_html += self.create_grm_map()
        page_html += """<script>
            let anchors = document.getElementsByTagName('a');
            for (let i=0; i < anchors.length; i++) {
                anchors[i].addEventListener('click', onSeatClick);
            }

            let lastElement = null;

            function onSeatClick(event) {
                event.preventDefault();
                let event_path = event.composedPath();
                console.log(event);

                for(let i=0; i < event_path.length; i++) {
                    if (event_path[i].classList.contains("seat")) {
                        let seatNumber = event_path[i].dataset.seat;
                        let compartmentNumber = event_path[i].dataset.compartment;
                        let compartmentDetailElement = document.getElementById("compartment-detail-" + compartmentNumber);

                        if (lastElement?.innerHTML) lastElement.innerHTML = "";
                        lastElement = compartmentDetailElement;
                        compartmentDetailElement.parentElement.scrollIntoView();

                        compartmentDetailElement.innerHTML = `<center><em><b>Seat: ${seatNumber}</b></em><br/>`
                            + event_path[i].dataset.compartmentName
                            + "</center><br/><br/>";

                        compartmentDetailElement.innerHTML += "<div style='text-align: center;'><div style='display: inline-block; text-align: left;'>"

                        trainSegments.forEach((segment) => {
                            compartmentDetailElement.innerHTML += `<li>${segment.name}: ${(segment.seats.includes(compartmentNumber + "_" + seatNumber)) ? "<green>Available</green>": "<red>Busy</red>"}</li>`
                        })

                        compartmentDetailElement.innerHTML += "</div></div>"
                        break
                    }
                }
            }

            function showSeat(segmentId) {
                let compartmentSvgs = document.getElementsByTagName('svg'),
                        filterTrainSegments = (segmentId !== undefined) ? trainSegments.slice(segmentId, segmentId + 1) : trainSegments;

                for (let i=0; i < compartmentSvgs.length; i++) {
                    let compartmentName = compartmentSvgs[i].dataset.name;
                    let compartmentNumber = compartmentName.split("_").slice(-1)[0];

                    let seatAnchors = compartmentSvgs[i].getElementsByClassName("seat");
                    for (let i=0; i < seatAnchors.length; i++) {
                        seatAnchors[i].dataset["seat"] = seatAnchors[i].href.baseVal;
                        seatAnchors[i].dataset["compartment"] = compartmentNumber;
                        seatAnchors[i].dataset["compartmentName"] = compartmentName;

                        let segmentsAvailable = filterTrainSegments.filter((segment) => segment.seats.includes(compartmentNumber + "_" + seatAnchors[i].href.baseVal))
                        if (segmentsAvailable.length === filterTrainSegments.length) {
                            let seatPathElements = seatAnchors[i].getElementsByTagName("path")
                            for (let ii=0; ii < seatPathElements.length; ii++) {
                                seatPathElements[ii].style.fill = "#0bc4a5"
                                seatPathElements[ii].style.stroke = "#24ffda"
                            }

                        } else if (segmentsAvailable.length === 0) {
                            let seatPathElements = seatAnchors[i].getElementsByTagName("path")
                            for (let ii=0; ii < seatPathElements.length; ii++) {
                                seatPathElements[ii].style.fill = "#7c0f06"
                                seatPathElements[ii].style.stroke = "#A6160A"
                            }

                        } else {
                            let seatPathElements = seatAnchors[i].getElementsByTagName("path")
                            for (let ii=0; ii < seatPathElements.length; ii++) {
                                seatPathElements[ii].style.fill = "#eeab00"
                                seatPathElements[ii].style.stroke = "#edcc8a"
                            }
                        }
                    }
                }
            }
            """
        page_html += "const trainSegments = " + json.dumps(segments) + ";\n"
        page_html += "showSeat();\n</script>\n</body>\n</html>"
        return page_html

    def search_train(self, train_number):
        self.retrieve_realtime(train_number)

        if len(self.train_schedule["StazioniNonFerme"]) < 2:
            raise UserError("Not enough stops...")

        return self.train_schedule

    def search_seats(self):
        self.get_session()
        segments = []

        for hop_index in range(1, len(self.train_schedule["StazioniNonFerme"])):
            self.clear_session()
            departure_station = self.train_schedule["StazioniNonFerme"][hop_index - 1]["LocationCode"]
            arrival_station = self.train_schedule["StazioniNonFerme"][hop_index]["LocationCode"]

            interval_start_time, interval_end_time = convert_departure_timestamp(
                self.train_schedule["StazioniNonFerme"][hop_index - 1]["EstimatedArrivalTime"]
            )

            segment_info = self.get_available_trains(departure_station, arrival_station,
                                                     interval_start_time, interval_end_time)

            segment_seats = set()
            for fare_sell_key in segment_info[1]:
                if self.hold_booking(segment_info[0], fare_sell_key):
                    seats = self.get_seat_availability(segment_info[0])
                    if not seats:
                        continue

                    if not self.train_type:
                        self.train_type = seats["Equipment"]["EquipmentType"]

                    # print(seats["Equipment"]["AvailableUnits"])
                    segment_seats.update([comp["CompartmentDesignator"] + "_" + seat["SeatDesignator"]
                                          for comp in seats["Equipment"]["Compartments"]
                                          for seat in comp["Seats"]
                                          if seat["Assignable"] and seat["SeatAvailability"] == 5])

            segments.append({
                "name": self.train_schedule["StazioniNonFerme"][hop_index - 1]["LocationDescription"] + " ➔ " +
                        self.train_schedule["StazioniNonFerme"][hop_index]["LocationDescription"],
                "code": segment_info[0],
                "seats": list(segment_seats)
            })
            # print(segment_info[0], len(segment_seats))

        return self.create_html(segments)


def convert_departure_timestamp(time_str):
    datetime_obj = datetime.datetime.combine(datetime.date.today(), datetime.time.fromisoformat(time_str))
    interval_start_unix = int((datetime_obj - datetime.timedelta(minutes=30)).timestamp()) * 1000
    interval_end_unix = int((datetime_obj + datetime.timedelta(hours=2)).timestamp()) * 1000
    return "/Date(%s)/" % interval_start_unix, "/Date(%s)/" % interval_end_unix
