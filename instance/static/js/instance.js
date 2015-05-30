
// App configuration //////////////////////////////////////////////////////////

var app = angular.module('InstanceApp', [
    'ngRoute',
    'ui.router',
    'restangular',
    'mm.foundation'
]);

app.config(function($httpProvider) {
    $httpProvider.defaults.headers.common['X-Requested-With'] = 'XMLHttpRequest';
});

app.config(function($stateProvider, $urlRouterProvider, RestangularProvider) {
    // For any unmatched url, send to /
    $urlRouterProvider.otherwise("/");

    $stateProvider
        .state('index', {
            url: "/",
            templateUrl: "/static/html/instance/index.html",
            controller: "Index"
        })
});


// Services ///////////////////////////////////////////////////////////////////

app.factory('OpenCraftAPI', function(Restangular) {
    return Restangular.withConfig(function(RestangularConfigurer) {
        RestangularConfigurer.setBaseUrl('/api/v1');
    });
});


// Function ///////////////////////////////////////////////////////////////////

function updateInstanceList($scope, OpenCraftAPI) {
    OpenCraftAPI.all("openedxinstance/").getList().then(function(instanceList) {
        console.log('Updating instance list', instanceList);
        $scope.instanceList = instanceList;

        if($scope.selected.instance){
            var updated_instance = null;
            _.each(instanceList, function(instance) {
                if(instance.pk === $scope.selected.instance.pk) {
                    updated_instance = instance;
                }
            });
            $scope.selected.instance = updated_instance;
        }
    }, function(response) {
        console.log('Error from server: ', response);
    });
}


// Controllers ////////////////////////////////////////////////////////////////

app.controller("Index", ['$scope', 'Restangular', 'OpenCraftAPI', '$q',
    function ($scope, Restangular, OpenCraftAPI, $q) {
        $scope.selected = Array();

        $scope.select = function(selection_type, value) {
            $scope.selected[selection_type] = value;
            console.log('Selected ' + selection_type + ':', value);
        };
    }
]);

app.controller("InstanceList", ['$scope', 'Restangular', 'OpenCraftAPI', '$q',
    function ($scope, Restangular, OpenCraftAPI, $q) {
        updateInstanceList($scope, OpenCraftAPI);

        swampdragon.onChannelMessage(function(channels, message) {
            console.log('Received websocket message', channels, message.data);

            if(message.data.type === 'server_update') {
                updateInstanceList($scope, OpenCraftAPI);
            }
        });

        swampdragon.ready(function() {
            swampdragon.subscribe('notifier', 'notification', null);
        });
    }
]);