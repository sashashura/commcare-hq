hqDefine("scheduling/js/conditional_alert_main", [
    'jquery',
    'knockout',
    'hqwebapp/js/initial_page_data',
    'data_interfaces/js/case_rule_criteria',
    'scheduling/js/create_schedule.ko',
    'data_interfaces/js/make_read_only',
], function ($, ko, initialPageData) {
    function basicInformationTab(formSubmitted, name) {
        var self = {};
        self.name = ko.observable(name);
        self.basicTabValid = ko.computed(function() {
            return !_.isEmpty(self.name().trim());
        });
        self.validateBasicTab = function() {
            if (self.basicTabValid()) {
                $("#rule-nav").removeClass("hidden");
            }
        };
        self.navigateToNav = function (navId) {
            $(navId).find('a').trigger('click');
        };
        self.handleBasicNavContinue = function () {
            $("#rule-nav").removeClass("hidden");
            $('#rule-nav').find('a').trigger('click');
        };
        return self;
    }

    $(function () {
        var formSubmitted = initialPageData.get('form_submitted');
        var name = initialPageData.get('rule_name');
        var basicInformation = basicInformationTab(formSubmitted, name);
        // setup tab
        basicInformation.validateBasicTab();
        $("#conditional-alert-basic-info-panel").koApplyBindings(basicInformation);
    });
});
