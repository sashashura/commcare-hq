hqDefine('users/js/invite_web_user',[
    'jquery',
    'knockout',
    'hqwebapp/js/initial_page_data',
    'hqwebapp/js/toggles',
    'hqwebapp/js/validators.ko',
], function (
    $,
    ko,
    initialPageData,
    toggles
) {
    'use strict';

    var inviteWebUserFormHandler = function () {
        var self = {};

        self.email = ko.observable()
            .extend({
                required: {
                    message: django.gettext("Please specify an email."),
                    params: true,
                },
                emailRFC2822: true,
            });

        self.showIdentityProviderMessage = ko.observable(false);
        self.identityProviderName = ko.observable('');
        self.trustedEmailDomain = ko.observable('');

        self.emailDelayed = ko.pureComputed(self.email)
            .extend({
                rateLimit: {
                    method: "notifyWhenChangesStop",
                    timeout: 400,
                },
                validation: {
                    async: true,
                    validator: function (val, params, callback) {
                        if (self.email.isValid()) {
                            self.showIdentityProviderMessage(false);

                            // ignore sso email domain check in production for now
                            if (!toggles.toggleEnabled('ENTERPRISE_SSO')) {
                                callback({ isValid: true });
                                return;
                            }

                            $.post(initialPageData.reverse('check_sso_trust'), {
                                username: self.email(),
                            }, function (result) {
                                self.showIdentityProviderMessage(!result.is_trusted);
                                self.identityProviderName(result.idp_name || '');
                                self.trustedEmailDomain(result.email_domain || '');
                                callback({ isValid: true });
                            });
                        }
                    },
                },
            });
        
        self.isSubmitEnabled = ko.computed(function () {
            return self.email.isValid()
                && self.emailDelayed.isValid()
                && !self.emailDelayed.isValidating();
        });

        return self;
    };

    $(function () {
        var formHandler = inviteWebUserFormHandler();
        $('#invite-web-user-form').koApplyBindings(formHandler);
    });
});
